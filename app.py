from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import date, datetime
from bs4 import BeautifulSoup
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///noten.db'
app.secret_key = b'gskjd%hsgd82jsd'
db = SQLAlchemy(app)
DATABASE = 'noten.db'
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
 
def extract_grades_from_html(html_content):
    """Parses the HTML content to extract grades."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_content, 'html.parser')
    all_grades = []

    
    rows = soup.find_all('tr')

    current_fach = None  

    for row in rows:
        
        fach_cell = row.find('td', {"style": "border-bottom: 0; padding-top: 2mm;"})
        if fach_cell:
            
            fach_parts = list(fach_cell.stripped_strings)
            current_fach = " ".join(fach_parts).strip()
            print(f"Gefundenes Fach: {current_fach}")
            continue

        
        detail_table = row.find('table', class_='clean')
        if detail_table and current_fach:
            detail_rows = detail_table.find_all('tr')[1:]  
            for detail_row in detail_rows:
                columns = detail_row.find_all('td')
                if len(columns) != 4:  
                    continue

                date = columns[0].get_text(strip=True)
                topic = columns[1].get_text(strip=True)
                grade_cell = columns[2]
                grade = grade_cell.contents[0].strip() if grade_cell.contents else None  
                weight = columns[3].get_text(strip=True)

                
                try:
                    grade = float(grade)
                    weight = float(weight)
                except ValueError:
                    print(f"Ungültige Note oder Gewichtung in Zeile: {detail_row}")
                    continue

                
                grade_entry = {
                    'fach': current_fach,
                    'date': date,
                    'topic': topic,
                    'grade': grade,
                    'weight': weight
                }
                all_grades.append(grade_entry)
                print(f"Note hinzugefügt: {grade_entry}")

    
    if not all_grades:
        print("Keine Noten extrahiert. Überprüfen Sie die HTML-Struktur.")
    else:
        print(f"Alle extrahierten Noten: {all_grades}")

    return all_grades



def save_grades_to_db(grades):
    """Saves the extracted grades to the database."""
    from datetime import datetime
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    def validate_grade_data(subject, grade, weight, date):
        """Validates a single row of grade data."""
        if not subject or not grade or not weight or not date:
            raise ValueError("Ein oder mehrere Felder sind leer.")

        
        if isinstance(grade, str):
            
            import re
            match = re.search(r'(\d+(\.\d+)?)', grade)
            if match:
                grade = float(match.group(1))
            else:
                raise ValueError(f"Keine gültige Note im Feld gefunden: {grade}")

        try:
            grade = float(grade)
            if grade < 1 or grade > 6:
                raise ValueError(f"Ungültige Note: {grade}")
        except ValueError:
            raise ValueError(f"Note ist keine gültige Zahl: {grade}")

        try:
            weight = float(weight)
            if weight <= 0:
                raise ValueError(f"Ungültige Gewichtung: {weight}")
        except ValueError:
            raise ValueError(f"Gewichtung ist keine gültige Zahl: {weight}")

        return subject, grade, weight, date


    processed_faecher = {}  

    for grade in grades:
        fach_name = grade['fach'].replace(')', ') ').replace('  ', ' ').strip()  
        logger.debug(f"Original Fachname: {grade['fach']}, Bearbeiteter Fachname: {fach_name}")

        wert = grade['grade']  
        datum = grade.get('date')
        gewichtung = grade['weight']  

        
        try:
            fach_name, wert, gewichtung, datum = validate_grade_data(fach_name, wert, gewichtung, datum)
        except ValueError as e:
            logger.warning(f"Ungültige Daten übersprungen: {e}")
            continue

        try:
            datum = datetime.strptime(datum, "%d.%m.%Y")  
        except ValueError:
            logger.error(f"Ungültiges Datum für Note: {datum}")
            continue

        
        logger.debug(f"Verarbeite Fach: {fach_name}, Note: {wert}, Datum: {datum}, Gewichtung: {gewichtung}")

        
        normalized_fach_name = fach_name.strip().lower()

        
        if normalized_fach_name in processed_faecher:
            fach = processed_faecher[normalized_fach_name]
        else:
            fach = Fach.query.filter_by(name=normalized_fach_name, user_id=current_user.id).first()
            if not fach:
                fach = Fach(name=fach_name.strip(), user_id=current_user.id)  
                db.session.add(fach)
                db.session.flush()  
            processed_faecher[normalized_fach_name] = fach

        
        existing_note = Note.query.filter_by(
            wert=wert, datum=datum, gewichtung=gewichtung, fach_id=fach.id, user_id=current_user.id
        ).first()

        if existing_note:
            
            logger.info(f"Note existiert bereits: Fach {fach_name}, Datum: {datum}, Wert: {wert}")
        else:
            neue_note = Note(wert=wert, datum=datum, gewichtung=gewichtung, fach=fach, user_id=current_user.id)
            db.session.add(neue_note)
            
            logger.info(f"Neue Note hinzugefügt: Fach {fach_name}, Datum: {datum}, Wert: {wert}")

    
    try:
        db.session.commit()
        logger.info("Noten erfolgreich gespeichert.")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Fehler beim Speichern der Noten: {e}")



class Fach(db.Model):
    __tablename__ = 'faecher'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    noten = db.relationship('Note', backref='fach', lazy=True, cascade="all, delete")
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    def calculate_pluspunkte(self):
        base_grade = 4.0  
        total_weighted_sum = 0.0
        total_weight = 0.0

        
        for note in self.noten:
            total_weighted_sum += note.wert * note.gewichtung
            total_weight += note.gewichtung

        if total_weight == 0:
            return 0.0  

        
        average = total_weighted_sum / total_weight

        
        rounded_average = int(average * 2 + 0.5) / 2

        
        if rounded_average >= base_grade:
            return round(rounded_average - base_grade, 2)
        else:
            return -round(base_grade - rounded_average, 2) * 2  
        
    def calculate_average(self):
        total_weighted_sum = sum(note.wert * note.gewichtung for note in self.noten)
        total_weight = sum(note.gewichtung for note in self.noten)
        if total_weight == 0:
            return 0.0
        return round(total_weighted_sum / total_weight, 3)

    def calculate_minimum_grade(self, desired_average, new_weight=1.0):
        total_weighted_sum = sum(note.wert * note.gewichtung for note in self.noten)
        total_weight = sum(note.gewichtung for note in self.noten)

        
        total_weight += new_weight

        
        minimum_grade = (desired_average * total_weight - total_weighted_sum) / new_weight
        return round(max(1.0, min(6.0, minimum_grade)), 3)  
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "noten": [note.to_dict() for note in self.noten],
            "average": self.calculate_average(),
            "pluspunkte": self.calculate_pluspunkte(),
        }


           

        
class Note(db.Model):
    __tablename__ = 'noten'
    id = db.Column(db.Integer, primary_key=True)
    wert = db.Column(db.Float, nullable=False)
    datum = db.Column(db.Date, nullable=False)
    gewichtung = db.Column(db.Float, default=1.0)  
    fach_id = db.Column(db.Integer, db.ForeignKey('faecher.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "wert": self.wert,
            "datum": self.datum.strftime("%Y-%m-%d"),
            "gewichtung": self.gewichtung,
        }

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    faecher = db.relationship('Fach', backref='user', lazy=True)

with app.app_context():
    db.create_all()

class User(UserMixin, User):  
    pass

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/logout', methods=["GET", "POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))



@app.route("/", methods=["GET", "POST"])
def index():
    if not current_user.is_authenticated:
        if request.method == "POST":
            action = request.form.get('action')
            if action == "register":
                username = request.form['username']
                password = request.form['password']
                if User.query.filter_by(username=username).first():
                    return render_template('index.html', error="Benutzername existiert bereits", show_login=True, faecher_data=[])
                hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
                new_user = User(username=username, password=hashed_password)
                db.session.add(new_user)
                db.session.commit()
                return render_template('index.html', message="Registrierung erfolgreich. Bitte einloggen.", show_login=True, faecher_data=[])
            elif action == "login":
                username = request.form['username']
                password = request.form['password']
                user = User.query.filter_by(username=username).first()  
                if user and check_password_hash(user.password, password):  
                    login_user(user)
                    return redirect(url_for('index'))
                return render_template('index.html', error="Ungültige Anmeldedaten", show_login=True, faecher_data=[])
        return render_template('index.html', show_login=True, faecher_data=[])

    
    faecher = Fach.query.filter_by(user_id=current_user.id).all()
    faecher_data = []
    for fach in faecher:
        fach.average = fach.calculate_average()
        fach.minimum_grade = fach.calculate_minimum_grade(4.0)  
        faecher_data = [fach.to_dict() for fach in faecher]
    total_average = 0
    total_pluspunkte = 0
    faecher_mit_noten = [fach for fach in faecher if len(fach.noten) > 0]
    fach_count = len(faecher_mit_noten)

    for fach in faecher:
        total_average += fach.calculate_average()
        total_pluspunkte += fach.calculate_pluspunkte()

    
    if fach_count > 0:
        total_average /= fach_count
    else:
        total_average = 0.0

    username = current_user.username

    return render_template(
        "index.html",
        faecher=faecher,
        total_average=round(total_average, 3),
        total_pluspunkte=total_pluspunkte,
        show_login = False,
        faecher_data=faecher_data,
        username=username
    )


   

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        try:
            html_content = request.form['html']
            grades = extract_grades_from_html(html_content)
            save_grades_to_db(grades)
            return redirect(url_for("index"))

        except Exception as e:
            return jsonify({'error': str(e)}), 400
        
    return render_template('upload.html')


@app.route("/<string:type>/<string:action>", methods=["GET", "POST"])
@app.route("/<string:type>/<string:action>/<int:fach_id>", methods=["GET", "POST"])
def handle_item(type, action, fach_id=None):
    if type == "fach":
        item = Fach.query.filter_by(id=fach_id, user_id=current_user.id).first() if fach_id else None
        if fach_id and not item:
            return "Unauthorized", 403  

        if request.method == "POST":
            name = request.form['name']
            if action == "add":
                new_fach = Fach(name=name, user_id=current_user.id)
                db.session.add(new_fach)
            elif action == "edit" and item:
                item.name = name
            db.session.commit()
            return redirect(url_for('index'))
        return render_template("handle.html", type="Fach", action=action, data=item)

    elif type == "note":
        
        item = Note.query.get(fach_id) if fach_id and action == "edit" else None
        fach = Fach.query.get(item.fach_id) if item else Fach.query.get(fach_id)


        if not fach:
            return "Fach nicht gefunden", 404
        
        if fach.user_id != current_user.id:
            return "Unauthorized", 403  
        

        
        existing_grades = [note.wert for note in fach.noten] if fach.noten else []
        existing_weights = [note.gewichtung for note in fach.noten] if fach.noten else []

        if request.method == "POST":
            try:
                wert = float(request.form['wert'])
                if not (1 <= wert <= 6):
                    return "Die Note muss zwischen 1 und 6 liegen", 400

                datum = datetime.strptime(request.form['datum'], '%Y-%m-%d').date()
                gewichtung = float(request.form.get('gewichtung', 1.0))

                if gewichtung <= 0:
                    return "Die Gewichtung muss größer als 0 sein", 400

                if action == "add":
                    new_note = Note(
                        wert=wert,
                        datum=datum,
                        gewichtung=gewichtung,
                        fach_id=fach_id,
                        user_id=current_user.id
                    )
                    db.session.add(new_note)
                elif action == "edit" and item:
                    item.wert = wert
                    item.datum = datum
                    item.gewichtung = gewichtung

                db.session.commit()
                return redirect(url_for('index'))

            except ValueError:
                return "Ungültige Eingabe", 400
            except Exception as e:
                return str(e), 500

        current_pluspunkte = fach.calculate_pluspunkte()

        note_index = -1
        if type == "note" and action == "edit" and item:
            note_index = next((index for index, note in enumerate(fach.noten) if note.id == item.id), -1)

        return render_template(
            "handle.html",
            type="Note",
            action=action,
            data=item,
            fach_id=fach_id,
            current_pluspunkte=current_pluspunkte,
            existing_grades=existing_grades,
            existing_weights=existing_weights,
            note_index=note_index,
        )






@app.route("/<string:type>/delete/<int:item_id>")
def delete_item(type, item_id):
    if type == "fach":
        
        fach = Fach.query.filter_by(id=item_id, user_id=current_user.id).first()
        if not fach:
            return "Unauthorized", 403  

        
        db.session.delete(fach)

    elif type == "note":
        
        note = Note.query.get_or_404(item_id)
        if note.fach.user_id != current_user.id:
            return "Unauthorized", 403  

        
        db.session.delete(note)

    else:
        return "Invalid type", 400  

    db.session.commit()
    return redirect(url_for('index'))

@app.route("/reset", methods=["POST"])
def reset():
    
    Note.query.filter_by(user_id=current_user.id).delete()
    Fach.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)

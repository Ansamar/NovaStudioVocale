# NovaStudioVocale_Web/gui.py
from flask import Flask, render_template, request
from core import genera_audio_web
import os

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), "output_audio")

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/genera', methods=['POST'])
def genera():
    testo = request.form['testo']
    voce = request.form['voce']
    filtri = request.form.getlist('filtri')
    audio_path = genera_audio_web(testo, voce, filtri)

    return f'''
        <h2>Audio generato!</h2>
        <audio controls src="{audio_path}"></audio><br>
        <a href="{audio_path}" download>Scarica l'audio</a>
    '''

if __name__ == '__main__':
    app.run(debug=True)


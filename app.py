import os
import subprocess
from pydub import AudioSegment
import streamlit as st
import datetime
import io
import shutil
import json
import re

st.write(f"KMP_DUPLICATE_LIB_OK nell'ambiente Streamlit: {os.environ.get('KMP_DUPLICATE_LIB_OK')}")

# --- Configurazione e cartelle ---
SPEAKER_DIR = "speaker_previews"
OUTPUT_DIR = "filtered_output_audio"
TEMP_PYDUB_OUTPUT_FOR_FFMPEG = "temp_pydub_for_ffmpeg_streamlit.wav"
TEMP_FILTER_PREVIEW = "temp_filter_preview_streamlit.wav"
TEMP_TTS_OUTPUT_WAV = "temp_tts_raw.wav"
TEMP_INPUT_AUDIO_FOR_PYDUB = "temp_input_audio_for_pydub.wav"

# Percorso al file del vocabolario JSON
# ASSICURATI CHE QUESTO PERCORSO SIA CORRETTO PER IL TUO SISTEMA
VOCABOLARIO_JSON_PATH = "/Users/marioansaldi/NovaStudioVocale/vocabolario.json"
# Testo predefinito per l'area di input
DEFAULT_TTS_TEXT = "Benvenuti in NovaStudioVocale! Scrivi qui il testo che vuoi trasformare in voce."

# Assicurati che le cartelle esistano
os.makedirs(SPEAKER_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs("assets", exist_ok=True)

# --- Funzione di applicazione filtri ---
def applica_filtri_audio(input_audio_bytes_or_path, output_path, pitch_semitoni=0, velocita_fattore=1.0, volume_db=0):
    """
    Applica filtri audio (pitch, velocità, volume) a un file audio.
    input_audio_bytes_or_path può essere BytesIO o un percorso file.
    """
    try:
        # Pulisci i file temporanei prima di iniziare
        if os.path.exists(TEMP_PYDUB_OUTPUT_FOR_FFMPEG):
            os.remove(TEMP_PYDUB_OUTPUT_FOR_FFMPEG)
        if os.path.exists(TEMP_INPUT_AUDIO_FOR_PYDUB):
            os.remove(TEMP_INPUT_AUDIO_FOR_PYDUB)

        # Carica l'audio usando pydub
        if isinstance(input_audio_bytes_or_path, io.BytesIO):
            # Se è BytesIO, salvalo temporaneamente per pydub
            with open(TEMP_INPUT_AUDIO_FOR_PYDUB, "wb") as f:
                f.write(input_audio_bytes_or_path.getvalue())
            audio = AudioSegment.from_file(TEMP_INPUT_AUDIO_FOR_PYDUB)
        elif isinstance(input_audio_bytes_or_path, str) and os.path.exists(input_audio_bytes_or_path):
            audio = AudioSegment.from_file(input_audio_bytes_or_path)
        else:
            raise ValueError("Input audio non valido. Deve essere BytesIO o un percorso file esistente.")
        
        # Applica il volume con pydub (più semplice qui)
        if volume_db != 0:
            audio = audio + volume_db
        
        # Esporta l'audio modificato dal volume in un file temporaneo per ffmpeg
        audio.export(TEMP_PYDUB_OUTPUT_FOR_FFMPEG, format="wav")

        filter_commands = []
        
        # Pitch (cambio di intonazione)
        if pitch_semitoni != 0:
            pitch_rate_factor = (2.0 ** (pitch_semitoni / 12.0))
            new_sample_rate = int(audio.frame_rate * pitch_rate_factor)
            filter_commands.append(f"asetrate={new_sample_rate},atempo={1/pitch_rate_factor}")

        # Velocità (tempo)
        if velocita_fattore != 1.0:
            current_speed_factor = velocita_fattore
            atempo_filters = []
            
            # FFmpeg atempo ha limiti di fattore, quindi applica in più passaggi se necessario
            while current_speed_factor > 2.0:
                atempo_filters.append("atempo=2.0")
                current_speed_factor /= 2.0
            while current_speed_factor < 0.5:
                atempo_filters.append("atempo=0.5")
                current_speed_factor /= 0.5 
            if current_speed_factor != 1.0: # Aggiungi l'ultimo fattore rimanente
                atempo_filters.append(f"atempo={current_speed_factor}")
            
            filter_commands.append(",".join(atempo_filters))

        # Esegui FFmpeg solo se ci sono filtri da applicare
        if filter_commands:
            filter_string = ",".join(filter_commands)
            ffmpeg_command = [
                "ffmpeg", "-y", "-i", TEMP_PYDUB_OUTPUT_FOR_FFMPEG,
                "-filter:a", filter_string,
                output_path 
            ]
            
            process = subprocess.run(ffmpeg_command, capture_output=True, text=True, check=False)
            
            if process.returncode != 0:
                st.error(f"ERRORE FFmpeg (stdout): {process.stdout}")
                st.error(f"ERRORE FFmpeg (stderr): {process.stderr}")
                raise Exception(f"FFmpeg ha fallito con codice {process.returncode}: {process.stderr}")
            
        else:
            # Se nessun filtro è applicato, copia semplicemente il file temporaneo all'output
            shutil.copy(TEMP_PYDUB_OUTPUT_FOR_FFMPEG, output_path)

        # Verifica che il file di output sia stato creato e non sia vuoto
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise Exception(f"Il file di output {output_path} non è stato creato correttamente o è vuoto.")

        return True, "Filtri applicati con successo."

    except Exception as e:
        # Pulisci i file temporanei in caso di errore
        if os.path.exists(TEMP_FILTER_PREVIEW): os.remove(TEMP_FILTER_PREVIEW)
        if os.path.exists(TEMP_PYDUB_OUTPUT_FOR_FFMPEG): os.remove(TEMP_PYDUB_OUTPUT_FOR_FFMPEG)
        if os.path.exists(TEMP_INPUT_AUDIO_FOR_PYDUB): os.remove(TEMP_INPUT_AUDIO_FOR_PYDUB)
        return False, f"❌ Errore nell'applicazione filtri: {e}"

# --- Funzione per generare audio da testo (TTS) con XTTS v2 ---
def genera_audio_base_xtts(testo, speaker_name):
    """
    Genera un file audio da testo usando il modello XTTS v2 di Coqui-AI TTS.
    """
    if not testo.strip():
        st.error("❌ Testo vuoto per la generazione vocale.")
        return None

    speaker_path = os.path.join(SPEAKER_DIR, f"{speaker_name}.wav")
    if not os.path.exists(speaker_path):
        st.error(f"❌ Voce dello speaker non trovata: {speaker_name}. Assicurati che il file '{speaker_name}.wav' sia nella cartella '{SPEAKER_DIR}'.")
        return None

    if os.path.exists(TEMP_TTS_OUTPUT_WAV):
        os.remove(TEMP_TTS_OUTPUT_WAV)

    tts_command = [
        "tts",
        "--model_name", "tts_models/multilingual/multi-dataset/xtts_v2",
        "--text", testo,
        "--speaker_wav", speaker_path,
        "--language_idx", "it",
        "--out_path", TEMP_TTS_OUTPUT_WAV
    ]

    try:
        process = subprocess.run(tts_command, check=True, capture_output=True, text=True)
        
        if not os.path.exists(TEMP_TTS_OUTPUT_WAV):
            raise Exception(f"Il file di output TTS '{TEMP_TTS_OUTPUT_WAV}' non è stato creato da tts.")
        
        file_size = os.path.getsize(TEMP_TTS_OUTPUT_WAV)
        if file_size == 0:
            raise Exception(f"Il file di output TTS '{TEMP_TTS_OUTPUT_WAV}' è vuoto (dimensione 0 bytes).")
            
        with open(TEMP_TTS_OUTPUT_WAV, "rb") as f:
            audio_bytes = io.BytesIO(f.read())
        audio_bytes.seek(0) # Riporta il "puntatore" all'inizio del BytesIO
        
        os.remove(TEMP_TTS_OUTPUT_WAV) # Pulisci il file temporaneo
        
        st.success("✔️ Testo convertito in voce con successo.")
        return audio_bytes

    except subprocess.CalledProcessError as e:
        error_output = e.stderr if e.stderr else "Nessun output di errore specifico."
        st.error(f"❌ Errore grave nel comando TTS (codice {e.returncode}):\n{error_output}")
        st.warning("Verifica che il modello XTTS v2 sia scaricato e funzionante correttamente (`tts --list_models` dovrebbe mostrare 'xtts_v2').")
        if os.path.exists(TEMP_TTS_OUTPUT_WAV): os.remove(TEMP_TTS_OUTPUT_WAV)
        return None
    except Exception as e:
        st.error(f"❌ Errore imprevisto durante la generazione audio base: {e}")
        st.warning("Assicurati che Coqui-AI TTS sia correttamente installato e nel PATH del tuo ambiente conda. Potrebbe essere un problema di dipendenze (es. PyTorch).")
        if os.path.exists(TEMP_TTS_OUTPUT_WAV): os.remove(TEMP_TTS_OUTPUT_WAV)
        return None

# --- Interfaccia Streamlit ---
st.set_page_config(
    page_title="NovaStudioVocale",
    page_icon="🎶",
    layout="wide"
)

# --- Inizializzazione Session State ---
# Variabile per tenere traccia del testo nell'area di input
if 'tts_text_input' not in st.session_state:
    st.session_state.tts_text_input = DEFAULT_TTS_TEXT

# Contatore per forzare il reset o l'aggiornamento dell'area di testo
# Ogni volta che questo contatore cambia, Streamlit re-renderizza il widget text_area.
if 'text_area_key_counter' not in st.session_state:
    st.session_state.text_area_key_counter = 0

# Variabile per l'audio base corrente (generato da TTS o caricato)
if 'base_audio_bytes' not in st.session_state:
    st.session_state.base_audio_bytes = None

# Variabile per l'audio filtrato più recente (per l'anteprima)
if 'last_filtered_audio_data' not in st.session_state:
    st.session_state.last_filtered_audio_data = None

# Variabile per tenere traccia dei filtri applicati all'ultima anteprima
if 'last_applied_filters' not in st.session_state:
    st.session_state.last_applied_filters = None

# --- Header e Logo ---
col_logo, col_title = st.columns([1, 4])

with col_logo:
    logo_path = os.path.join("assets", "logo.png")
    if os.path.exists(logo_path): 
        st.image(logo_path, width=110) 
    else:
        st.warning(f"Logo '{logo_path}' non trovato. Assicurati che il file sia lì.")


with col_title:
    st.title("🎶 NovaStudioVocale")
    st.markdown("Crea audio da testo con voci personalizzate e applica filtri audio.")

st.markdown("---")

# --- Selezione Voce Speaker e Generazione Audio ---
st.header("🗣️ Generazione Vocale da Testo")

speaker_list = [f.replace(".wav", "") for f in os.listdir(SPEAKER_DIR) if f.endswith(".wav")]

if not speaker_list:
    # Crea un dummy speaker se non ci sono voci per evitare errori
    dummy_speaker_path = os.path.join(SPEAKER_DIR, "dummy_speaker.wav")
    if not os.path.exists(dummy_speaker_path):
        AudioSegment.silent(duration=1000).export(dummy_speaker_path, format="wav")
    speaker_list.append("dummy_speaker")
    st.warning(f"Nessuna voce trovata nella cartella '{SPEAKER_DIR}'. Creato 'dummy_speaker.wav' di esempio. Carica i tuoi file .wav per voci reali.")

col_speaker_select, col_speaker_preview = st.columns([1, 1])

with col_speaker_select:
    selected_speaker = st.selectbox(
        "Seleziona Voce Speaker:",
        options=speaker_list,
        index=0 if speaker_list else 0,
        help="Scegli una delle voci disponibili per la sintesi vocale."
    )

with col_speaker_preview:
    if selected_speaker:
        speaker_audio_path = os.path.join(SPEAKER_DIR, f"{selected_speaker}.wav")
        if os.path.exists(speaker_audio_path):
            st.markdown(f"**Esempio Voce '{selected_speaker}':**")
            st.audio(speaker_audio_path, format="audio/wav", start_time=0)
        else:
            st.error("File audio speaker non trovato nel percorso specificato.")


with st.expander("Altre Opzioni di Input Testo"):
    text_upload_file = st.file_uploader(
        "Carica un file di testo (.txt) per la sintesi vocale",
        type=["txt"],
        help="Carica un file contenente il testo da convertire. Il contenuto sovrascriverà l'area di testo."
    )
    if text_upload_file is not None:
        string_data = text_upload_file.getvalue().decode("utf-8")
        st.session_state.tts_text_input = string_data
        # IMPT: Incrementa il contatore per assicurare che il text_area si aggiorni
        st.session_state.text_area_key_counter += 1
        st.success(f"File '{text_upload_file.name}' caricato. Controlla l'area di testo qui sotto.")
        st.rerun() # Forza un rerun per aggiornare la text_area immediatamente


# Area di testo principale.
# Il valore viene preso da st.session_state.tts_text_input.
# La key è dinamica per forzare il re-rendering quando tts_text_input cambia programmaticamente.
user_input_text = st.text_area(
    "Testo da convertire in audio:",
    value=st.session_state.tts_text_input, # Inizializza con il valore corrente della session state
    height=150,
    key=f"main_text_input_area_{st.session_state.text_area_key_counter}" # Key dinamica
)

# Dopo che l'area di testo è stata renderizzata, aggiorna st.session_state.tts_text_input
# con il valore effettivo che l'utente ha inserito.
# Questo è cruciale per catturare le modifiche dell'utente tra i rerun.
st.session_state.tts_text_input = user_input_text


# --- Strumenti di Modifica Testo ---
st.markdown("#### Strumenti di Modifica Testo")
col_text_tools = st.columns(4) # Quattro colonne per i bottoni

with col_text_tools[0]:
    if st.button("Pausa Liturgica (. a ...)", help="Sostituisce i punti (.) con tre puntini (...) e rimuove i caratteri speciali come virgolette (', «, »).", key="liturgical_pause_button"):
        # `st.session_state.tts_text_input` contiene già il testo corrente grazie alla riga `st.session_state.tts_text_input = user_input_text`
        modified_text = st.session_state.tts_text_input 
        modified_text = modified_text.replace(".", "...")
        modified_text = modified_text.replace("«", "").replace("»", "").replace('"', '').replace("'", "")
        st.session_state.tts_text_input = modified_text # Aggiorna la session state con il testo modificato
        # IMPT: Aggiorna contatore e reruns per tutti gli aggiornamenti programmatici del testo
        st.session_state.text_area_key_counter += 1
        st.rerun()

with col_text_tools[1]:
    if st.button("Punto a Capo", help="Aggiunge un ritorno a capo dopo ogni punto (.).", key="newline_after_dot_button"):
        modified_text = st.session_state.tts_text_input # Prendi il testo attualmente nell'area di input
        modified_text = modified_text.replace(".", ".\n")
        st.session_state.tts_text_input = modified_text # Aggiorna la session state con il testo modificato
        # IMPT: Aggiorna contatore e reruns per tutti gli aggiornamenti programmatici del testo
        st.session_state.text_area_key_counter += 1
        st.rerun()

with col_text_tools[2]:
    if st.button("Correggi Pronuncia", help=f"Usa il vocabolario in {VOCABOLARIO_JSON_PATH} per correggere la pronuncia di parole specifiche.", key="correct_pronunciation_button"):
        modified_text = st.session_state.tts_text_input # Prendi il testo attualmente nell'area di input
        
        if not os.path.exists(VOCABOLARIO_JSON_PATH):
            st.error(f"❌ File vocabolario.json non trovato: {VOCABOLARIO_JSON_PATH}")
        else:
            try:
                with open(VOCABOLARIO_JSON_PATH, "r", encoding="utf-8") as f:
                    vocabolario_raw = json.load(f)
                
                vocabolario_for_replacement = {
                    word_key: replacements[0] 
                    for word_key, replacements in vocabolario_raw.items() 
                    if isinstance(replacements, list) and len(replacements) > 0
                }
                # Ordina le parole da sostituire dalla più lunga alla più corta per evitare sostituzioni parziali
                sorted_words = sorted(vocabolario_for_replacement.keys(), key=len, reverse=True)
                
                for word_to_replace in sorted_words:
                    replacement_word = vocabolario_for_replacement[word_to_replace]
                    # Usa regex per la sostituzione di parole intere (\b), case-sensitive
                    # re.escape() è importante se la parola da cercare contiene caratteri speciali regex
                    pattern = r'\b' + re.escape(word_to_replace) + r'\b'
                    modified_text = re.sub(pattern, replacement_word, modified_text)
                
                st.session_state.tts_text_input = modified_text # Aggiorna la session state con il testo modificato
                # IMPT: Aggiorna contatore e reruns per tutti gli aggiornamenti programmatici del testo
                st.session_state.text_area_key_counter += 1
                st.success("✔️ Pronuncia corretta usando il vocabolario.")
                st.rerun()
            except json.JSONDecodeError:
                st.error(f"❌ Errore nel leggere il file JSON. Assicurati che '{VOCABOLARIO_JSON_PATH}' sia un JSON valido.")
            except Exception as e:
                st.error(f"❌ Errore durante la correzione pronuncia: {e}")

with col_text_tools[3]:
    if st.button("Reset Testo", help="Cancella il testo nell'area di input.", key="reset_text_button"):
        # Questo è l'unico punto in cui resettiamo esplicitamente al testo di benvenuto
        st.session_state.tts_text_input = DEFAULT_TTS_TEXT
        st.session_state.text_area_key_counter += 1 # Incrementa il contatore per cambiare la key del text_area
        st.session_state.base_audio_bytes = None # Resetta anche l'audio generato
        st.session_state.last_filtered_audio_data = None # Resetta l'anteprima dei filtri
        st.session_state.last_applied_filters = None # Resetta i valori dei filtri applicati
        st.rerun() # Forza un rerun per applicare il reset

st.markdown("---")

col_generate_button, _ = st.columns([1, 2])

with col_generate_button:
    if st.button("✨ Genera Audio dalla Voce Selezionata", key="generate_tts_button", type="primary"):
        if st.session_state.tts_text_input.strip() and selected_speaker:
            with st.spinner("Generando voce... Potrebbe volerci del tempo per la prima volta."):
                generated_audio_bytes = genera_audio_base_xtts(st.session_state.tts_text_input, selected_speaker)
                if generated_audio_bytes:
                    st.session_state.base_audio_bytes = generated_audio_bytes
                    st.session_state.last_filtered_audio_data = None
                    st.session_state.last_applied_filters = None
                    st.info("Audio generato! Puoi ascoltarlo nella sezione 'Audio Base' qui sotto o applicare i filtri.")
                else:
                    st.error("Impossibile generare la voce. Controlla i messaggi di errore sopra e le installazioni Coqui-AI TTS/ffmpeg.")
        else:
            st.warning("Per favore, inserisci del testo e seleziona una voce.")

st.markdown("---")

# --- Sezione Audio Base (Originale) ---
st.header("🎵 Audio Base (Originale)")
if st.session_state.base_audio_bytes is not None:
    st.info("Questo è l'audio generato dal testo o caricato da file, prima di qualsiasi filtro.")
    st.audio(st.session_state.base_audio_bytes, format="audio/wav", start_time=0)
else:
    st.info("Genera un audio dal testo qui sopra o carica un file per vederlo apparire qui come 'audio base'.")

st.markdown("---")

# --- Sezione Filtri Audio ---
st.header("🎚️ Applica Filtri Audio")
st.markdown("Regola i cursori per modificare l'audio corrente. Clicca 'Applica Filtri' per generare l'anteprima.")

col_sliders, col_preview_button = st.columns([1, 1])

with col_sliders:
    pitch_semitoni = st.slider(
        "Pitch (Semitoni)",
        min_value=-12, max_value=12, value=0, step=1,
        key="pitch_slider",
        help="Modifica la tonalità dell'audio senza alterare la velocità."
    )
    velocita_fattore = st.slider(
        "Velocità (Fattore)",
        min_value=0.25, max_value=4.0, value=1.0, step=0.05,
        key="speed_slider",
        help="Modifica la velocità di riproduzione. Il pitch rimane invariato."
    )
    volume_db = st.slider(
        "Volume (dB)",
        min_value=-20, max_value=20, value=0, step=1,
        key="volume_slider",
        help="Aumenta o diminuisce il volume generale dell'audio."
    )

with col_preview_button:
    if st.session_state.base_audio_bytes is None:
        st.info("Genera un audio dal testo o carica un file per iniziare ad applicare i filtri.")
    else:
        if st.button("▶️ Applica Filtri e Genera Anteprima", key="apply_filters_button", type="secondary"):
            with st.spinner("Applicando i filtri..."):
                input_bytes_copy = io.BytesIO(st.session_state.base_audio_bytes.getvalue())
                
                success, message = applica_filtri_audio(
                    input_bytes_copy, 
                    TEMP_FILTER_PREVIEW, # output to temp file
                    pitch_semitoni, velocita_fattore, volume_db
                )

                if success:
                    st.session_state.last_filtered_audio_data = open(TEMP_FILTER_PREVIEW, "rb").read()
                    # Salva i valori dei filtri applicati
                    st.session_state.last_applied_filters = {
                        "pitch": pitch_semitoni,
                        "speed": velocita_fattore,
                        "volume": volume_db
                    }
                    st.success("Filtri applicati. Premi play per ascoltare l'anteprima.")
                    if os.path.exists(TEMP_FILTER_PREVIEW):
                        os.remove(TEMP_FILTER_PREVIEW)
                else:
                    st.error(f"❌ Errore nell'applicazione filtri: {message}")
                    st.session_state.last_filtered_data = None # Correggi da last_filtered_audio_data
                    st.session_state.last_applied_filters = None
        
        if st.session_state.last_filtered_audio_data:
            st.markdown("#### Anteprima Audio Filtrato:")
            if st.session_state.last_applied_filters:
                p = st.session_state.last_applied_filters['pitch']
                v = st.session_state.last_applied_filters['speed']
                vol = st.session_state.last_applied_filters['volume']
                st.markdown(f"**Valori applicati:** Pitch: {p} semitoni, Velocità: {v:.2f}x, Volume: {vol} dB")
            st.audio(st.session_state.last_filtered_audio_data, format="audio/wav", start_time=0)


# --- Sezione Carica Audio Esistente (per applicare filtri a file esterni) ---
st.markdown("---")
st.header("⬆️ Carica Audio Esistente per Modifica")
uploaded_file = st.file_uploader(
    "Carica un file audio (.wav) dal tuo computer", 
    type=["wav"], 
    key="upload_existing_audio_button", 
    help="Questo audio diventerà l'audio base su cui applicare i filtri."
)

if uploaded_file is not None:
    st.session_state.base_audio_bytes = io.BytesIO(uploaded_file.read())
    st.session_state.base_audio_bytes.seek(0)
    st.session_state.last_filtered_audio_data = None
    st.session_state.last_applied_filters = None
    # IMPT: Incrementa il contatore per assicurare che il text_area si aggiorni
    st.session_state.text_area_key_counter += 1 
    st.success(f"✔️ File '{uploaded_file.name}' caricato come base.")
    st.rerun() # Forza un rerun per aggiornare l'interfaccia

st.markdown("---")

# --- Sezione Salva Audio Finale ---
st.header("💾 Salva il tuo Audio Finale")

output_filename_input = st.text_input(
    "Nome file di output (senza estensione .wav)",
    value=f"audio_nova_studio_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}",
    key="output_filename_input"
)

if st.button("✔️ Salva Audio con Filtri nel Computer", key="save_final_audio_button", type="primary"):
    if st.session_state.base_audio_bytes is not None:
        if not output_filename_input.strip():
            st.error("Per favor, inserisci un nome per il file di output.")
        else:
            final_output_path = os.path.join(OUTPUT_DIR, output_filename_input)
            if not final_output_path.lower().endswith(".wav"):
                final_output_path += ".wav"

            with st.spinner(f"Salvataggio in corso di {os.path.basename(final_output_path)}..."):
                input_bytes_copy = io.BytesIO(st.session_state.base_audio_bytes.getvalue())

                success, message = applica_filtri_audio(
                    input_bytes_copy, 
                    final_output_path,  
                    pitch_semitoni, velocita_fattore, volume_db
                )
                if success:
                    st.success(f"✔️ Audio salvato in: {final_output_path}")
                    try:
                        with open(final_output_path, "rb") as f:
                            download_data = f.read()
                        st.download_button(
                            label="Scarica il file filtrato",
                            data=download_data,
                            file_name=os.path.basename(final_output_path),
                            mime="audio/wav",
                            key="download_button"
                        )
                    except Exception as e:
                        st.error(f"Impossibile leggere il file per il download: {e}")
                else:
                    st.error(f"❌ Errore durante il salvataggio: {message}")
    else:
        st.warning("Per favor, genera o carica un audio prima di salvare.")
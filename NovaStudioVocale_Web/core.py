# NovaStudioVocale_Web/core.py
import os
from app import genera_audio  # Modifica questo se la funzione ha un nome diverso

def genera_audio_web(testo, voce, filtri):
    # Chiama la funzione esistente nel tuo progetto
    audio_path = genera_audio(testo, voce, filtri)
    return audio_path


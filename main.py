import speech_recognition as sr
import webbrowser
import pyttsx3
import random
import musicLibrary
import time

recognizer = sr.Recognizer()



def speak(text):
    engine = pyttsx3.init()
    engine.stop()
    engine.say(text)
    engine.runAndWait()


def play_random_music():
    song = random.choice(list(musicLibrary.music.values()))
    speak("Playing random music")
    webbrowser.open_new_tab(song)


def process_command(command):
    command = command.lower()


    if "open google" in command:
        speak("Opening Google")
        webbrowser.open_new_tab("https://www.google.com")

    elif "open youtube" in command:
        speak("Opening YouTube")
        webbrowser.open_new_tab("https://www.youtube.com")

    elif "facebook" in command:
        speak("Opening Facebook")
        webbrowser.open_new_tab("https://www.facebook.com")

    elif "linkedin" in command:
        speak("Opening LinkedIn")
        webbrowser.open_new_tab("https://www.linkedin.com")


    elif "play" in command:
        for key in musicLibrary.music:
            if key in command:
                speak(f"Playing {key.lower()} music")
                webbrowser.open_new_tab(musicLibrary.music[key])
                return

        play_random_music()

    else:
        speak("Sorry, I didn't understand that")


if __name__ == "__main__":
    speak("Initializing Mark")

    while True:
        try:

            with sr.Microphone() as source:
                print("Waiting for wake word...")
                audio = recognizer.listen(source, timeout=3, phrase_time_limit=5)

            command = recognizer.recognize_google(audio)
            print("You said:", command)


            if "mark" in command.lower():
                speak("yes sir")
                time.sleep(0.5)

                with sr.Microphone() as source:
                    print("Listening for command...")
                    audio = recognizer.listen(source, timeout=3, phrase_time_limit=5)

                command = recognizer.recognize_google(audio)
                print("Command:", command)

                process_command(command)

        except Exception as e:
            print("Error:", e)
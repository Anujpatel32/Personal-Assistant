import pytest
import queue
import tts_engine
import voice_thread


class MockApp:
    def __init__(self):
        self.stop_speaking_flag = False
        import threading
        self.active_engine_lock = threading.Lock()
        self.active_engine = None


def test_tts_engine_stop():
    mock_app = MockApp()
    tts_engine.init_tts(mock_app)
    tts_engine.set_speaking_active(True)
    assert tts_engine.is_speaking() is True

    tts_engine.stop()
    assert mock_app.stop_speaking_flag is True
    assert tts_engine._is_speaking_active is False


def test_speech_worker_clear_queue():
    mock_app = MockApp()
    tts_engine.init_tts(mock_app)
    speech_q = queue.Queue()
    audio_q = queue.Queue()

    worker = voice_thread.SpeechQueueWorker(speech_q, audio_q)
    worker.speech_queue.put((0, "hello world"))
    worker.audio_queue.put((0, "sapi", "hello world"))

    assert not worker.speech_queue.empty()
    assert not worker.audio_queue.empty()
    initial_gen = worker.generation_id

    worker.clear_queue()

    assert worker.speech_queue.empty()
    assert worker.audio_queue.empty()
    assert worker.generation_id == initial_gen + 1


def test_stop_command_interception():
    mock_app = MockApp()
    voice_thread.init_voice_thread(mock_app, "system", None, None)

    # Instantiate VoiceAssistantThread without launching the blocking QThread run loop
    thread = voice_thread.VoiceAssistantThread.__new__(voice_thread.VoiceAssistantThread)
    thread.running = False
    thread.generation_id = 0
    thread.speech_queue = queue.Queue()
    thread.audio_queue = queue.Queue()
    thread.speech_worker = voice_thread.SpeechQueueWorker(thread.speech_queue, thread.audio_queue)
    import collections
    thread._spoken_phrases = collections.deque(maxlen=20)
    thread.chat_history = []
    thread._awake_until = 0.0
    thread._STAY_AWAKE_SECS = 8

    # Test stop commands
    for stop_cmd in ["stop", "stop talking", "shut up", "be quiet", "cancel", "pause", "enough"]:
        res = thread.process_assistant_logic(stop_cmd)
        assert res == "Stopped."


def test_self_echo_detection():
    thread = voice_thread.VoiceAssistantThread.__new__(voice_thread.VoiceAssistantThread)
    import collections
    thread._spoken_phrases = collections.deque(maxlen=20)

    # Record some spoken text
    thread._record_spoken_text("Solar energy is radiant light and heat from the Sun.")
    assert len(thread._spoken_phrases) == 1

    # Exact or substring match should be detected as echo
    assert thread._is_self_echo("solar energy is radiant light") is True
    assert thread._is_self_echo("radiant light and heat from the sun") is True

    # Real user command should NOT be detected as echo
    assert thread._is_self_echo("what is the weather today") is False
    assert thread._is_self_echo("play music") is False
    assert thread._is_self_echo("stop") is False


def test_clean_text_for_tts_removes_asterisks():
    # Bold, italic, bullets, dangling asterisks
    cases = [
        ("**bold text**", "bold text"),
        ("*italic text*", "italic text"),
        ("***bold italic***", "bold italic"),
        ("* item one\n* item two", "item one item two"),
        ("Dangling * asterisk", "Dangling asterisk"),
        ("Multiple *** stars ** everywhere *", "Multiple stars everywhere"),
        ("Here is **point 1**: and *point 2*", "Here is point 1: and point 2"),
    ]
    for inp, expected in cases:
        cleaned = tts_engine.clean_text_for_tts(inp)
        assert "*" not in cleaned
        assert cleaned == expected



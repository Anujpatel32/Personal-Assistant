# 🐱 MEOW — AI Desktop Personal Assistant

**MEOW** (Me-ow) is a full-featured AI-powered desktop personal assistant for Windows with voice control, gesture recognition, a web dashboard, and multi-LLM support.

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?logo=windows)
![License](https://img.shields.io/badge/License-MIT-green)

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🎤 **Voice Assistant** | Wake word activation ("Hey Mark"), speech recognition, and natural TTS responses |
| 🖥️ **Desktop Mascot** | Animated PySide6 companion widget that lives on your desktop |
| 🌐 **Web Dashboard** | Real-time system HUD, chat interface, task manager, knowledge base — accessible from any device on your network |
| 🧠 **Multi-LLM Support** | Route queries to Gemini, Groq, NVIDIA, OpenRouter, or a local LLaMA model |
| 👋 **Gesture Control** | MediaPipe hand tracking for cursor control, volume adjustment, and window management |
| 🔌 **Plugin System** | Hot-loadable plugins with a marketplace UI |
| 📱 **Mobile Dashboard** | Responsive mobile-friendly web interface |
| 💡 **Proactive Intelligence** | Weather alerts, task reminders, and contextual suggestions |
| 😊 **Emotion Engine** | Mood tracking and emotionally aware responses |
| 🎯 **Action Planner** | Multi-step agentic task execution |
| 📸 **Screen Memory** | Screenshot capture, OCR, and contextual screen awareness |
| 🌍 **Internet Agent** | Web browsing and information retrieval |
| 🎵 **Music Control** | Play playlists, detect currently playing media |
| 💻 **PC Control** | Open apps, manage system settings, automation commands |
| 📝 **Knowledge Base** | Upload documents (PDF, DOCX, TXT) for RAG-powered Q&A |
| 🎨 **Voice Personality** | Switch between casual, concise, and professional response styles |

---

## ☁️ Cloud-only AI

MEOW's chat and reasoning engine uses configured cloud providers only:
- Google Gemini
- Groq
- NVIDIA NIM
- OpenRouter

Local LLM inference (TinyLlama / GGUF via llama.cpp) is not supported. If a selected
provider is unavailable, MEOW tries other providers for which an API key is configured.
If no provider is configured or all configured providers fail, MEOW reports that state
instead of loading a local model.

This change does not remove local speech/audio components, optional Kokoro TTS,
document storage, or the ChromaDB vector store used by the knowledge-base feature.
Those components are separate from local generative chat inference.

## 🚀 Quick Start

### Prerequisites
- **Python 3.11+**
- **Windows 10/11** (required for system integration features)
- **Microphone** (for voice control)
- **Webcam** (optional, for gesture control)

### Installation

```bash
# Clone the repository
git clone https://github.com/anujpatel32/MEOW-Personal-Assistant.git
cd MEOW-Personal-Assistant

# Create a virtual environment
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install pywin32 (Windows system integration)
pip install pywin32
python venv\Scripts\pywin32_postinstall.py -install

# Install Playwright browsers (for web agent)
playwright install chromium
```

### Configuration

On first launch, MEOW will create a `memory.json` file. Configure your API keys through the **Settings** tab in the web dashboard, or by voice command.

Supported LLM providers:
- **Google Gemini** — get a key at [aistudio.google.com](https://aistudio.google.com)
- **Groq** — get a key at [console.groq.com](https://console.groq.com)
- **NVIDIA NIM** — get a key at [build.nvidia.com](https://build.nvidia.com)
- **OpenRouter** — get a key at [openrouter.ai](https://openrouter.ai)
- **Local LLaMA** — place a `.gguf` model file in the project directory

### Launch

```bash
# Run the assistant
python companion.py

# Or use the batch launcher
Launch_MEAO.bat
```

The desktop mascot will appear, and the web dashboard will be available at `http://localhost:5005`.

---

## 🏗️ Architecture

```
companion.py          ← Entry point: wires everything together
├── mascot_widget.py  ← PySide6 desktop mascot UI
├── app.py            ← Flask web server + REST API
│   ├── templates/
│   │   ├── index.html    ← Web dashboard
│   │   └── mobile.html   ← Mobile view
│   ├── memory_manager.py ← Persistent memory & learning
│   ├── knowledge_manager.py ← Document RAG indexing
│   └── plugin_manager.py ← Runtime plugin loading
├── voice_thread.py   ← Speech recognition & voice pipeline
├── tts_engine.py     ← Text-to-speech (SAPI / ElevenLabs / Kokoro)
├── llm_router.py     ← Multi-provider LLM API routing
├── pc_control.py     ← System commands & app control
├── gesture_control.py← MediaPipe hand tracking
├── emotion_engine.py ← Mood tracking & emotional responses
├── proactive_engine.py ← Proactive suggestions
├── action_planner.py ← Multi-step task planning
├── screen_memory.py  ← Screenshot capture & OCR
├── vision_control.py ← Screen analysis via LLM vision
├── internet_agent.py ← Web browsing agent
├── voice_personality.py ← Response style presets
├── code_builder.py   ← Code generation capabilities
├── musicLibrary.py   ← Music playlist links
└── plugins/
    └── system_health.py ← System health monitoring plugin
```

---

## 📡 API Endpoints

The Flask server exposes these REST endpoints on port `5005`:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web dashboard |
| `/api/state` | GET | System state (CPU, RAM, GPU, battery, etc.) |
| `/api/chat` | POST | Send a chat message |
| `/api/tasks` | GET/POST/DELETE | Manage to-do tasks |
| `/api/documents` | GET/POST/DELETE | Knowledge base documents |
| `/api/plugins` | GET/POST | Plugin marketplace |
| `/api/queue` | GET/POST/DELETE | Autonomous task queue |
| `/api/gesture/toggle` | POST | Toggle gesture control |
| `/api/settings` | GET/POST | Assistant settings & API keys |

---

## 🎤 Voice Commands

| Command | Action |
|---------|--------|
| "Hey Mark" | Wake word — activates listening |
| "Open YouTube / Google / ..." | Opens websites |
| "Play [playlist name]" | Plays music from library |
| "What's the weather?" | Current weather report |
| "Take a screenshot" | Captures and analyzes screen |
| "Activate gesture control" | Starts hand tracking |
| "Be more concise / casual / professional" | Changes response style |
| "Shut down" | Exits the assistant |

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

## 👤 Author

**Anuj Patel** — [@anujpatel32](https://github.com/anujpatel32)


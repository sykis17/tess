# TESS Engine - Roadmap

- [x] **Phase 1:** Set up local Docker infrastructure (FastAPI, Redis, Celery).

- [x] **Phase 2:** Build LLM connection interfaces (Asynchronous wrappers for Gemini & Ollama).

- [x] **Phase 3:** Create the core LangGraph structure (Wide Receiver & Presenter nodes).

- [x] **Phase 4:** Connect the Celery worker to execute the LangGraph chain and stream results back via Redis/WebSockets.

- [x] **Phase 5:** Build the React frontend prototype to receive and dynamically render Panels.

- [x] **Phase 6:** Deploy the local setup to a Hetzner production server.
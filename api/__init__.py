"""API — camada FastAPI que expõe a Presentation Layer.

A API NUNCA acessa diretamente o Core (Pipeline, EventBus,
EventStore, Searcher, Ranking, etc.). Toda comunicação ocorre
exclusivamente através da Presentation Layer existente.

Estrutura:
  - routers/      : endpoints REST agrupados por domínio.
  - schemas/      : modelos Pydantic para request/response.
  - dependencies/ : injeção de Presentation Services.
  - websocket/    : endpoint WebSocket para streaming de eventos.
  - startup/      : composition root (inicializa Core + Presentation).
  - health/       : healthcheck da própria API.
  - middlewares/  : middlewares FastAPI (CORS, logging, versioning).
  - exceptions/   : handlers de exceções FastAPI.
"""

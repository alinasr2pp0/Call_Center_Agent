#  Call Center Agent
### Intelligent Customer Support Platform | منصة ذكية لخدمة العملاء

An AI-assisted customer support platform that combines an intelligent customer portal, an administrative dashboard, knowledge-base retrieval, automated ticket management, and optional AI-powered voice services — all backed by a lightweight SQLite database.

منصة ذكية لإدارة خدمة العملاء ومراكز الاتصال، تجمع بين بوابة للعملاء، ولوحة تحكم إدارية، ومحرك للبحث في قاعدة المعرفة، وإدارة التذاكر والتصعيد إلى الموظفين، مع إمكانية دمج خدمات الذكاء الاصطناعي والصوت والمكالمات الهاتفية.

**Built with Python, FastAPI, SQLite, Retrieval-Augmented Generation (RAG), and modular AI integrations.**

---

## 1. Project Overview | نظرة عامة

Traditional customer support systems often rely on repetitive manual responses, fragmented knowledge sources, and time-consuming ticket resolution.

This project introduces an intelligent support workflow designed to retrieve relevant knowledge, generate helpful responses when appropriate, and escalate unresolved issues to human agents.

The platform provides:

- **Customer Portal:** Account registration, authentication, support requests, and personalized interactions.
- **AI-Assisted Support:** Knowledge-based answers using BM25 retrieval and optional semantic search.
- **Intelligent Escalation:** Unresolved or low-confidence requests can be transferred to human support.
- **Voice Integration:** Optional speech-to-text and text-to-speech capabilities.
- **Automated Follow-Up:** Optional outbound calls to verify whether an issue has been resolved.
- **Administrative Dashboard:** Ticket management, knowledge-base administration, user management, and operational metrics.
- **Document Ingestion:** Upload supported documents and convert their extracted text into searchable knowledge articles.
- **Lightweight Database:** SQLite is created automatically, eliminating the need for a separately configured database server.

The goal is not simply to automate responses, but to build a structured support workflow that combines automation, traceable knowledge retrieval, and human intervention when needed.

## 2. Key Features | المميزات الرئيسية

### Intelligent Customer Support
- Accept customer problems through text.
- Support voice input when the required speech provider is configured.
- Search the knowledge base using BM25 keyword retrieval.
- Enable hybrid semantic retrieval using embeddings and optional reranking.
- Generate AI-assisted responses through an optional LLM integration.
- Escalate questions when the available knowledge is insufficient.

### Customer Portal
- Customer registration and login.
- Submit support requests and communicate with the support system.
- Select a response persona to customize the interaction style.
- Access the customer-facing interface through a web browser.

### Administrative Dashboard
- Monitor support tickets and their statuses.
- Review operational performance metrics.
- Manage the knowledge base and uploaded documents.
- Manage customers and response personas.
- Support role-based access for administrators and agents.
- Provide staff management capabilities for the superadmin.

### AI and Voice Integrations
- **OpenRouter:** Optional LLM-powered response generation and reformulation.
- **Groq:** Optional speech recognition and speech synthesis.
- **Tavily:** Optional fallback web search, subject to the configured integration and its eligibility rules.
- **Vonage Voice:** Optional automated follow-up calls.
- **Local Embeddings:** Optional semantic search without requiring a hosted embedding API after the model has been downloaded.

### Document Intelligence
Supported document formats:
- PDF
- DOCX
- TXT
- Markdown (MD)

Uploaded documents are processed into searchable knowledge articles. The original document is not retained by the documented ingestion workflow; extracted text is stored instead.

**Document limit:** 10 MB per file. Scanned PDFs and password-protected files are not supported by the documented pipeline.

## 3. System Architecture | معمارية النظام

The application follows a modular architecture that separates the web interface, business logic, knowledge retrieval, and persistence.

```text
                  CUSTOMER
                      |
                      v
              Customer Portal
                      |
                      v
                FastAPI Backend
                      |
          +-----------+-----------+
          |           |           |
          v           v           v
      Support      Security     Ticket
      Services     & Roles     Management
          |
          v
       Knowledge Retrieval
          |
          +----------------------+
          |                      |
          v                      v
     BM25 Search          Optional Semantic
                          Search & Reranking
          |                      |
          +-----------+----------+
                      |
                      v
              Answer Evaluation
                      |
              +-------+-------+
              |               |
              v               v
       Knowledge-Based     Human Agent
           Response        Escalation
              |
              v
      Optional Voice Follow-Up

       SQLite Database
       Persistent Storage
```

### Architecture Principles
- **Separation of concerns:** API routes, business services, retrieval, and database operations have distinct responsibilities.
- **Modularity:** External AI providers are optional integrations rather than mandatory requirements for basic operation.
- **Graceful degradation:** The system can continue using keyword retrieval if optional semantic-search components fail.
- **Data-driven metrics:** Dashboard metrics are calculated from recorded application data.
- **Lightweight deployment:** SQLite stores application data in a single database file.

## 4. Technology Stack | التقنيات المستخدمة

| Component | Technology | Purpose |
|---|---|---|
| Backend | Python, FastAPI | API endpoints and application logic |
| Database | SQLite | Persistent application data |
| Authentication | JWT, PBKDF2-SHA256 | Authentication and password protection |
| Knowledge Retrieval | BM25 | Keyword-based document retrieval |
| Semantic Search | Sentence Transformers / multilingual embeddings | Meaning-based retrieval |
| Vector Storage | SQLite or optional Qdrant | Store and retrieve embeddings |
| Hybrid Retrieval | Reciprocal Rank Fusion (RRF) | Combine keyword and semantic rankings |
| Reranking | Optional cross-encoder | Improve retrieved-result ordering |
| LLM | OpenRouter | AI-assisted answer generation |
| Speech Recognition | Groq | Optional speech-to-text |
| Speech Synthesis | Groq | Optional text-to-speech |
| Web Search | Tavily | Optional restricted fallback search |
| Telephony | Vonage Voice | Optional automated follow-up calls |
| Frontend | HTML, CSS, JavaScript | Customer portal and admin dashboard |
| Testing | Python unittest | Automated application and retrieval tests |

## 5. How It Works | آلية العمل

1. **Customer Request:** A customer submits a support question through the portal.
2. **Knowledge Retrieval:** The backend searches the available knowledge base using BM25 or the configured hybrid retrieval pipeline.
3. **Context Evaluation:** The system determines whether the retrieved information is sufficient to support a response.
4. **Response Generation:** If configured, an LLM can reformulate the retrieved information into a more natural response.
5. **Escalation:** Requests that cannot be resolved reliably can be assigned to a human agent.
6. **Follow-Up:** If voice and telephony integrations are configured, the system can initiate a follow-up call to verify resolution.
7. **Monitoring:** Ticket statuses and recorded operational events feed the administrative dashboard.

The precise behavior depends on the enabled integrations and the application's configured confidence thresholds.

## 6. Knowledge Base and Semantic Search

The platform supports two retrieval modes.

**Default mode — BM25**

A lightweight keyword-based search system that can operate without external AI credentials. Arabic text normalization and Egyptian Arabic dialect handling improve matching for supported expressions.

**Optional mode — Hybrid Semantic Retrieval**

Semantic search can be enabled using local embedding models and a supported vector store.

The optional retrieval pipeline can combine:
- Keyword-based BM25 retrieval.
- Dense vector similarity.
- Reciprocal Rank Fusion (RRF).
- Optional cross-encoder reranking.

This approach helps retrieve relevant information even when a customer's wording differs from the wording used in the knowledge base.

Similarity thresholds should be calibrated against representative support questions before production use.

## 7. Database and Persistence

SQLite is the default database, designed to provide a simple deployment experience.

- No separate database server is required.
- The database file is created automatically.
- Application records are stored persistently.
- Sample personas and knowledge articles can be initialized automatically.
- Optional embedding records can be stored in SQLite.
- Qdrant can be used as an alternative vector store when configured.

**Default database location:** `data/call_center.db`

The exact tables and relationships depend on the application's database models and migrations.

## 8. Security and Access Control

The project includes several security-oriented mechanisms:

- Password hashing using PBKDF2-SHA256.
- JWT-based authentication.
- Role-based access control.
- Login attempt rate limiting.
- Signed webhook requests for the configured telephony integration.
- Environment-based configuration for credentials and secrets.
- Git exclusions for sensitive configuration and local database files.

### Application Roles

| Role | Permissions |
|---|---|
| `superadmin` | Full system access, including staff management |
| `admin` | Administrative metrics, knowledge base, customers, personas, and supported data-management operations |
| `agent` | Read-only access to assigned application information as defined by the implementation, including tickets and knowledge resources |

### Production Security Recommendations

Before public deployment:
- Configure HTTPS.
- Use strong, unique credentials and securely managed environment variables.
- Remove development-only credentials and mock login values from frontend files.
- Validate webhook signatures and protect externally accessible endpoints.
- Configure persistent storage and backups.
- Use a shared rate-limiting backend such as Redis if multiple application workers are deployed.
- Test authorization, file uploads, and tenant/customer data isolation.
- Verify all external integrations in a controlled environment.

Security features should be validated through testing and code review before the application is considered production-ready.

## 9. Quick Start | التشغيل السريع

### Requirements
- Python installed.
- Git (optional, for cloning the repository).
- Internet access for installing dependencies and downloading optional AI models.

### Linux / macOS

```bash
./scripts/run.sh
```

### Windows

```bat
scripts\run.bat
```

### Manual Installation

```bash
python -m venv .venv
```

Activate the virtual environment:

```bash
# Linux / macOS
source .venv/bin/activate

# Windows
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r backend/requirements.txt
```

Optionally configure environment variables:

```bash
# Linux / macOS
cp .env.example .env
```

```bat
:: Windows
copy .env.example .env
```

Start the backend:

```bash
cd backend
python run.py
```

### Application URLs

| Service | URL |
|---|---|
| Customer Portal | http://127.0.0.1:8001/ |
| Admin Dashboard | http://127.0.0.1:8001/admin |
| API Documentation | http://127.0.0.1:8001/docs |
| Health Check | http://127.0.0.1:8001/health |

On the first run, a `superadmin` account is created. If `SUPERADMIN_PASSWORD` is not configured, the application prints a randomly generated password to the console.

**Important:** Save the generated password securely before closing the terminal.

## 10. Environment Configuration

External integrations can be enabled independently.

| Variable | Purpose |
|---|---|
| `SUPERADMIN_PASSWORD` | Initial superadmin password |
| `OPENROUTER_API_KEY` | LLM integration credentials |
| `OPENROUTER_MODEL` | Configured language model |
| `GROQ_API_KEY` | Speech processing credentials |
| `WHISPER_MODEL` | Speech recognition model |
| `STT_LANGUAGE` | Speech recognition language |
| `GROQ_TTS_MODEL` | Text-to-speech model |
| `GROQ_TTS_VOICE` | Configured voice |
| `TAVILY_API_KEY` | Optional web search credentials |
| `EMBEDDING_PROVIDER` | Embedding provider selection |
| `EMBEDDING_MODEL` | Embedding model identifier |
| `VECTOR_STORE` | Vector storage backend |
| `QDRANT_URL` | Optional Qdrant connection |
| `RERANKER_ENABLED` | Enable or disable reranking |

Use `.env.example` as the authoritative reference for the variables supported by the current implementation.

Never commit real API keys, passwords, private keys, or production database files to version control.

## 11. Testing and Quality Assurance

Run the test suite from the backend directory:

```bash
cd backend
python -m unittest discover -s tests -v
```

For the optional semantic retrieval configuration:

```bash
EMBEDDING_PROVIDER=local python -m unittest discover -s tests -v
```

On Windows, set environment variables using the appropriate Command Prompt or PowerShell syntax.

Recommended additional validation:
- Authentication and authorization tests.
- Ticket lifecycle and escalation tests.
- Document ingestion and duplicate-upload tests.
- Retrieval quality and confidence-threshold evaluation.
- Failure handling for unavailable AI providers.
- Voice and telephony integration tests.
- Database persistence and migration tests.
- Performance and concurrency testing.

A successful test run should be documented with the environment, test command, and actual results. Features that have not been tested end-to-end should not be described as fully verified.

## 12. Project Structure

```text
call-center-agent/
├── backend/
│   ├── app/
│   │   ├── agent/
│   │   ├── rag/
│   │   ├── routers/
│   │   ├── services/
│   │   ├── models.py
│   │   ├── schemas.py
│   │   ├── config.py
│   │   └── database.py
│   ├── tests/
│   ├── requirements.txt
│   └── run.py
├── frontend/
│   ├── index.html
│   └── admin.html
├── data/
├── scripts/
│   ├── run.sh
│   └── run.bat
├── .env.example
├── .gitignore
└── README.md
```

This is a conceptual representation of the documented project layout. Keep the README synchronized with the actual repository structure.

## 13. Current Scope and Limitations

The platform is designed to provide a lightweight and extensible customer-support foundation. The following limitations should be considered:

- AI-powered responses require the relevant provider configuration.
- Speech processing and automated calls require their respective credentials and external service setup.
- Semantic search requires optional dependencies and model initialization.
- Scanned documents require OCR support, which is not included in the described ingestion pipeline.
- Confidence thresholds and retrieval quality need evaluation using representative customer queries.
- SQLite is suitable for lightweight deployments, but high-concurrency production workloads may require a different persistence strategy.
- Real-world telephony, security, performance, and deployment behavior must be verified before production use.

## 14. Future Enhancements

Potential development directions include:

- Agent performance and workload analytics.
- Multilingual support and improved Egyptian Arabic understanding.
- Streaming voice conversations and improved interruption handling.
- Redis-backed rate limiting and background task processing.
- Advanced retrieval evaluation and automated regression tests.
- Docker-based deployment and continuous integration.
- Monitoring, structured logs, and distributed tracing.
- Integration with CRM and external ticketing platforms.
- Customer satisfaction surveys and resolution-quality analytics.

These items are proposed enhancements, not claims about existing functionality.

## 15. Project Objective

The objective is to build a modular, AI-assisted customer-support platform that reduces repetitive support work, improves access to organizational knowledge, and provides a clear path from automated assistance to human resolution.

By combining knowledge retrieval, optional LLM integration, structured ticket management, and extensible voice services, the project establishes a foundation for more efficient and measurable customer support.

---

**Project Category:** AI Engineering · Customer Support Automation · Backend Development · Retrieval-Augmented Generation

**Core Technologies:** Python · FastAPI · SQLite · BM25 · Semantic Search · RAG · JWT · REST APIs

**Optional Integrations:** OpenRouter · Groq · Tavily · Vonage · Qdrant

**Deployment Philosophy:** Lightweight by default, modular by design, and extensible toward production requirements.

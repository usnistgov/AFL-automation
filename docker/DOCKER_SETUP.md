# AFL-Automation Docker Compose Setup Progress

## Completed Tasks

### 1. OrchestratorDriver Dockerfile ✅

**File**: [Dockerfile.orchestrator](Dockerfile.orchestrator)

**Summary**:
- Multi-stage Docker build for efficient image size
- Base image: `python:3.12-slim` (lightweight)
- Installs AFL-automation package via pip
- Exposes port 5000 (configurable via `AFL_ORCHESTRATOR_PORT` env var)
- Includes health check for container orchestration
- Runs via: `python -m AFL.automation.orchestrator.OrchestratorDriver`

**Key Features**:
- Uses launcher.py which loads configuration from `~/.afl/config.json`
- Supports Flask APIServer with queued/unqueued task dispatch
- Integrates with Client objects for communication with other services
- Configuration-driven: reads from PersistentConfig

**Docker Runtime**:
```bash
docker build -f Dockerfile.orchestrator -t afl-orchestrator:latest .
docker run -p 5000:5000 -e AFL_ORCHESTRATOR_PORT=5000 afl-orchestrator:latest
```

---

### 2. OrchestratorDriver Tests ✅

**File**: [test/test_orchestrator.py](test/test_orchestrator.py)

**Test Coverage**:
- Configuration validation (required keys, client config, instrument config)
- Composition format validation (mass_fraction, volume_fraction, concentration, molarity)
- Default values verification
- Client management and initialization
- Status tracking (UUID tracking, campaign names, status strings)
- Error handling for invalid configurations

**Key Test Classes**:
1. `TestOrchestratorDriverConfiguration` - Config validation & errors
2. `TestOrchestratorDriverClient` - Client initialization & management
3. `TestOrchestratorDriverStatus` - Status & UUID tracking
4. `TestOrchestratorDriverDefaults` - Default value validation

**Running Tests**:
```bash
pytest test/test_orchestrator.py -v
```

---

## Next Steps: Service Implementation Order

### Recommended Order: 1️⃣ **Tiled Server** → 2️⃣ Mixing Server → 3️⃣ Instrument Control → 4️⃣ Agent Server

---

## Service Analysis & Recommendations

### Overview of All 5 Services

| Service | Location | Type | Dependencies | Complexity | Port |
|---------|----------|------|--------------|------------|------|
| **Orchestrator** ✅ | `AFL/automation/orchestrator/OrchestratorDriver.py` | Driver/API | Flask, Client | Medium | 5000 |
| **Tiled Server** 🎯 | `tiled/config.yml` | Data Catalog | SQLite, Uvicorn | Low | 8000 |
| **Mixing Server** | `AFL/automation/mixing/BioSANSPrepare.py` | Driver/API | MassBalance, EIC | High | 5001 |
| **Instrument Control** | `AFL/automation/instrument/BioSANS.py` | Driver/API | EPICS, EIC | High | 5002 |
| **Agent Server** | `AFL/agent/double_agent/AgentDriver.py` | Driver/API | TensorFlow?, ML | Very High | 5003 |

---

### Detailed Service Analysis

#### 1. **Tiled Server** (RECOMMENDED NEXT) 🎯

**Why this first?**
- **Lowest complexity**: Primarily a configuration file with database backend
- **No inter-service dependencies**: Standalone, can be validated immediately
- **Foundation for others**: All other services will write/read data to Tiled
- **Simple Docker setup**: Just needs uvicorn + tiled package
- **Easiest to debug**: If this fails, it's config or database issues

**What it does**:
- Provides HTTP API for time-series and tabular data storage
- SQLite backend for metadata catalog
- File storage for actual data files
- RESTful interface for reading/writing measurements

**Dockerfile approach**:
```dockerfile
FROM python:3.12-slim
RUN pip install tiled[server]
COPY tiled/config.yml /app/config.yml
EXPOSE 8000
CMD ["tiled", "serve", "config", "--config", "/app/config.yml"]
```

**Key configuration**:
- SQLite database URI: `sqlite+aiosqlite:///catalog.db`
- Data storage directory: `data/`
- Port: 8000
- Optional API key authentication

---

#### 2. **Mixing Server** (After Tiled)

**Why second?**
- **Depends on Tiled**: Writes prepared sample data to Tiled
- **Medium complexity**: Inherits from both `MassBalance` and `Driver`
- **EIC client**: Needs external EIC connection (can be mocked for testing)
- **Preparatory role**: Prepares samples before measurements

**What it does**:
- Calculates mass balance for sample preparation
- Controls mixing hardware (Opentrons?)
- Validates sample feasibility
- Writes results to Tiled

**Dependencies**:
- `eic_client.EICClient` - External instrument control
- `MassBalance` - Internal mass balance calculator
- Tiled server (for data storage)

**Dockerfile considerations**:
- Needs EIC_TOKEN environment variable
- May need hardware access (docker run with device mounts)
- Depends on network access to Tiled service

---

#### 3. **Instrument Control Server** (After Mixing)

**Why third?**
- **Depends on Tiled**: Writes measurement data
- **EPICS dependency**: Talks to EPICS control system (BioSANS beamline)
- **Complex hardware integration**: Nexus file writing, transmission calculation
- **Measurement role**: Performs actual X-ray scattering measurements

**What it does**:
- Controls BioSANS beamline (ORNL)
- Collects scattering data
- Writes Nexus HDF5 files
- Manages sample transmission measurements

**Dependencies**:
- `epics` package - EPICS control system interface
- `h5py` - HDF5 file writing
- `eic_client.EICClient` - Instrument control
- Tiled server (for metadata)

**Dockerfile considerations**:
- Needs EPICS_CA_ADDR_LIST environment variable
- May need custom EPICS client libraries
- Network access to beamline control systems

---

#### 4. **Agent Server** (Last)

**Why last?**
- **Most complex**: Machine learning/AI orchestration
- **Depends on all others**: Reads from Tiled, orchestrates Mixing & Instrument
- **External dependencies**: May have TensorFlow, PyTorch, or other ML frameworks
- **Data-driven**: Needs populated Tiled database to function

**What it does**:
- Active learning orchestration
- Recommends next samples to prepare/measure
- ML model-based decision making
- Feedback loop optimization

**Dependencies**:
- All other services (orchestrator, tiled, mixing, instrument)
- Potentially heavy ML libraries (TensorFlow, scikit-learn, etc.)
- Tiled client for data access

**Dockerfile considerations**:
- Largest image (ML frameworks)
- Needs GPU support potentially (nvidia-docker)
- Complex initialization with model loading

---

## Docker Compose Architecture

```
┌─────────────────────────────────────────────────────┐
│           Orchestrator (5000)                       │
│         (Central Loop Controller)                   │
├─────────────────────────────────────────────────────┤
│  ↓            ↓              ↓              ↓       │
│Mixing     Tiled        Instrument       Agent       │
│(5001)    (8000)        (5002)          (5003)       │
│  ↓            ↓              ↓              ↓       │
│Database   Catalog       Beamline         AI        │
│  ↓            ↑              ↓              ↓       │
└─────────────────────────────────────────────────────┘
          ↑                                   ↑
          │─── All services write data ──────┘
          │─── Tiled aggregates & serves ───→
```

---

## Dockerfile Template for Future Services

```dockerfile
# Multi-stage build pattern used for Orchestrator
FROM python:3.12-slim as builder
WORKDIR /build
COPY . .
RUN pip install --user --no-cache-dir .

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
COPY . .
EXPOSE <PORT>
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s \
    CMD python -c "import requests; requests.get('http://localhost:<PORT>/status')" || exit 1
CMD ["python", "-m", "<SERVICE.MODULE>"]
```

---

## Configuration Strategy

### Environment Variables (in docker-compose)
```yaml
environment:
  - AFL_SYSTEM_SERIAL=BioSANS-v1
  - TILED_SERVER=http://tiled:8000
  - TILED_API_KEY=${TILED_API_KEY}
  - EIC_TOKEN=${EIC_TOKEN}
  - EPICS_CA_ADDR_LIST=beamline.local
```

### Volume Mounts
```yaml
volumes:
  - ./tiled/data:/app/data  # Tiled data storage
  - ./config:/root/.afl     # AFL global config
  - /var/log/afl:/logs      # Centralized logging
```

---

## Testing Strategy

For each service, create `test/test_<service>.py`:

1. **Unit tests**: Configuration validation, method behavior
2. **Integration tests**: Service communication via HTTP
3. **Docker tests**: Image builds successfully, runs, healthcheck passes

```bash
# Test individual service
pytest test/test_orchestrator.py -v

# Test with docker-compose
docker-compose up -d
pytest test/integration/ -v --timeout=30
docker-compose down
```

---

## Summary & Recommendation

**✅ Completed**:
- Orchestrator Dockerfile (multi-stage, optimized)
- Orchestrator tests (14 test methods covering config, clients, status)

**🎯 Recommended Next Step**: Build Tiled Server
- Simplest service (config file + database)
- Foundation for other services
- No external service dependencies
- Easiest validation path

**Implementation for Tiled**:
1. Create `Dockerfile.tiled` (simple uvicorn setup)
2. Create `test/test_tiled.py` (config validation, API tests)
3. Document tiled configuration options
4. Test database initialization and persistence

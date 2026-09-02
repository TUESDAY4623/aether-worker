# Aether Model — Model Metadata and Partitioning

Defines model capability profiles, placement manifests, and partitioning strategies.

## Modules

| File | Purpose |
|---|---|
| `manifest.py` | ModelManifest, PartitionPlan, ModelPartitioner |
| `capability_registry.py` | ModelCapabilities, ModelCapabilityRegistry, built-in models |

## Model Manifest (`manifest.py`)

### ManifestEntry

Describes a single tensor/layer within a model:

```python
@dataclass
class ManifestEntry:
    tensor_id: str          # Unique ID: "{model_id}_layer_{i}"
    tensor_name: str        # Human-readable name
    dtype: str              # Quantization format (int4, int8, fp16, ...)
    shape: list[int]        # Tensor dimensions
    byte_size: int          # Size in bytes
    primary_device: str     # Primary device ID
    replica_device: str     # Replica device ID (optional)
    residency_priority: str # "warm", "hot", "cold"
    required_backend: str   # Required compute backend
    checksum: str           # SHA-256 checksum
```

### ModelManifest

Complete placement manifest for one model:

```python
manifest = ModelManifest(
    model_id="llama3-8b",
    model_name="LLaMA 3 8B",
    quantization_format="int4",
    total_params=8_000_000_000,
    layer_count=32,
)
```

### ModelPartitioner

Two partitioning strategies:

| Strategy | Description |
|---|---|
| `memory_only` | Round-robin distribution of all tensors across workers |
| `layer_offload` | First and last layers stay local; middle layers distributed |

```python
partitioner = ModelPartitioner(scheduler=scheduler)
plan = partitioner.partition(
    manifest=manifest,
    device_ids=["worker-1", "worker-2"],
    strategy="layer_offload",
    local_device="laptop",
)
```

## Model Capability Registry (`capability_registry.py`)

### ModelCapabilities

Machine-readable profile for a model:

```python
@dataclass
class ModelCapabilities:
    model_id: str
    model_name: str
    architecture_family: ArchitectureFamily  # TRANSFORMER, LLAMA, MISTRAL, ...
    supported_runtimes: list[str]            # ["llama.cpp", "ollama", "vllm"]
    supported_data_types: list[DataType]     # FLOAT16, INT4, ...
    quantization_formats: list[QuantizationFormat]
    required_operators: list[str]            # ["embedding", "attention", "ffn", ...]
    preferred_accelerators: list[str]        # ["cpu", "npu", "gpu"]
    minimum_memory_mb: int
    distributed_compatibility: DistributedCompatibility  # PIPELINE, TENSOR, HYBRID, EXPERT
    known_limitations: list[str]
    context_length_profile: dict[str, int]
    memory_footprint_mb: dict[str, int]
```

### Built-in Models

| Model ID | Name | Min Memory | Distributed |
|---|---|---|---|
| `llama3-8b` | LLaMA 3 8B | 5,200 MB | PIPELINE |
| `llama3-70b` | LLaMA 3 70B | 40,000 MB | HYBRID |
| `mistral-7b` | Mistral 7B | 4,500 MB | PIPELINE |
| `phi3-mini` | Phi-3 Mini | 2,500 MB | NONE |
| `gemma-2b` | Gemma 2B | 1,500 MB | NONE |
| `mixtral-8x7b` | Mixtral 8x7B | 35,000 MB | EXPERT |

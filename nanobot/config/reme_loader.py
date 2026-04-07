"""ReMe configuration loader - loads config from external YAML file."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from loguru import logger
from pydantic import BaseModel, Field


class RemeLLMConfig(BaseModel):
    """LLM configuration for ReMe."""

    backend: Literal["openai"] = "openai"
    model_name: str = ""
    api_key: str = ""
    base_url: str = ""


class RemeEmbeddingConfig(BaseModel):
    """Embedding configuration for ReMe."""

    backend: Literal["openai"] = "openai"
    model_name: str = "text-embedding-3-small"
    dimensions: int = 512
    api_key: str = ""
    base_url: str = ""


class RemeVectorStoreConfig(BaseModel):
    """Vector store configuration for ReMe."""

    backend: Literal["local", "chroma", "qdrant", "elasticsearch", "pgvector"] = "local"
    collection_name: str = "nanobot_memory"
    persist_directory: str = ""


class RemeRetrievalConfig(BaseModel):
    """Memory retrieval configuration."""

    top_k: int = 10
    enable_time_filter: bool = True
    similarity_threshold: float = 0.5


class RemeMemoryTypeConfig(BaseModel):
    """Configuration for a single memory type."""

    enabled: bool = True
    max_memories: int = 0  # 0 means unlimited


class RemeMemoryTypesConfig(BaseModel):
    """Configuration for all memory types."""

    personal: RemeMemoryTypeConfig = Field(default_factory=RemeMemoryTypeConfig)
    procedural: RemeMemoryTypeConfig = Field(default_factory=RemeMemoryTypeConfig)
    tool: RemeMemoryTypeConfig = Field(default_factory=RemeMemoryTypeConfig)


class RemeProfileConfig(BaseModel):
    """Profile file synchronization configuration."""

    enabled: bool = True
    sync_to_files: bool = True
    soul_file: str = "SOUL.md"
    user_file: str = "USER.md"
    memory_file: str = "memory/MEMORY.md"


class RemeAdvancedConfig(BaseModel):
    """Advanced configuration options."""

    deduplication: bool = True
    expiration_days: int = 0  # 0 means never expire
    batch_size: int = 20
    debug: bool = False


class RemeConfig(BaseModel):
    """Complete ReMe configuration loaded from YAML file."""

    enabled: bool = True
    working_dir: str = ".reme"

    llm: RemeLLMConfig = Field(default_factory=RemeLLMConfig)
    embedding: RemeEmbeddingConfig = Field(default_factory=RemeEmbeddingConfig)
    vector_store: RemeVectorStoreConfig = Field(default_factory=RemeVectorStoreConfig)
    retrieval: RemeRetrievalConfig = Field(default_factory=RemeRetrievalConfig)
    memory_types: RemeMemoryTypesConfig = Field(default_factory=RemeMemoryTypesConfig)
    profile: RemeProfileConfig = Field(default_factory=RemeProfileConfig)
    advanced: RemeAdvancedConfig = Field(default_factory=RemeAdvancedConfig)

    # Runtime-filled fields (inherited from nanobot)
    _inherited_llm_model: str = ""
    _inherited_api_key: str = ""
    _inherited_base_url: str = ""

    @classmethod
    def load_from_file(cls, config_path: Path) -> "RemeConfig":
        """Load configuration from YAML file."""
        if not config_path.exists():
            logger.warning(f"ReMe config file not found: {config_path}, using defaults")
            return cls()

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            config = cls(**data)
            logger.info(f"Loaded ReMe config from {config_path}")
            return config
        except Exception as e:
            logger.error(f"Failed to load ReMe config: {e}, using defaults")
            return cls()

    def inherit_from_nanobot(
        self,
        default_model: str = "",
        api_key: str = "",
        base_url: str = "",
    ) -> "RemeConfig":
        """Inherit configuration from nanobot (fill empty fields)."""
        self._inherited_llm_model = default_model
        self._inherited_api_key = api_key
        self._inherited_base_url = base_url
        return self

    def get_effective_llm_config(self) -> dict[str, Any]:
        """Get effective LLM config (merged with inherited values)."""
        return {
            "backend": self.llm.backend,
            "model_name": self.llm.model_name or self._inherited_llm_model,
            "api_key": self.llm.api_key or self._inherited_api_key,
            "base_url": self.llm.base_url or self._inherited_base_url,
        }

    def get_effective_embedding_config(self) -> dict[str, Any]:
        """Get effective Embedding config (merged with inherited values)."""
        return {
            "backend": self.embedding.backend,
            "model_name": self.embedding.model_name,
            "dimensions": self.embedding.dimensions,
            "api_key": self.embedding.api_key or self._inherited_api_key,
            "base_url": self.embedding.base_url or self._inherited_base_url,
        }

    def get_effective_vector_store_config(self) -> dict[str, Any]:
        """Get effective vector store config."""
        return {
            "backend": self.vector_store.backend,
            "collection_name": self.vector_store.collection_name,
            "persist_directory": self.vector_store.persist_directory,
        }

    # Compatibility properties (used by adapter)
    @property
    def llm_model_name(self) -> str:
        return self.llm.model_name or self._inherited_llm_model

    @property
    def llm_backend(self) -> str:
        return self.llm.backend

    @property
    def embedding_model_name(self) -> str:
        return self.embedding.model_name

    @property
    def embedding_dimensions(self) -> int:
        return self.embedding.dimensions

    @property
    def vector_store_backend(self) -> str:
        return self.vector_store.backend

    @property
    def collection_name(self) -> str:
        return self.vector_store.collection_name

    @property
    def retrieve_top_k(self) -> int:
        return self.retrieval.top_k

    @property
    def enable_time_filter(self) -> bool:
        return self.retrieval.enable_time_filter

    @property
    def enable_profile_files(self) -> bool:
        return self.profile.enabled

    @property
    def sync_profile_to_files(self) -> bool:
        return self.profile.sync_to_files

    @property
    def enable_personal_memory(self) -> bool:
        return self.memory_types.personal.enabled

    @property
    def enable_procedural_memory(self) -> bool:
        return self.memory_types.procedural.enabled

    @property
    def enable_tool_memory(self) -> bool:
        return self.memory_types.tool.enabled


def load_reme_config(workspace: Path, nanobot_config: dict | None = None) -> RemeConfig:
    """
    Main entry point for loading ReMe configuration.

    Args:
        workspace: nanobot workspace path
        nanobot_config: nanobot config dict (for inheritance)

    Returns:
        RemeConfig instance
    """
    from nanobot.config.loader import get_config_path

    # Get config directory (same level as config.json)
    config_dir = get_config_path().parent

    # 1. Find config file (support multiple locations)
    # Priority: config_dir > workspace
    config_paths = [
        config_dir / "reme.yaml",
        config_dir / "reme.yml",
        workspace / "reme.yaml",
        workspace / "reme.yml",
    ]

    config_path = None
    for path in config_paths:
        if path.exists():
            config_path = path
            break

    # 2. Load config
    config = RemeConfig.load_from_file(config_path) if config_path else RemeConfig()

    # 3. Inherit from nanobot config
    if nanobot_config:
        defaults = nanobot_config.get("agents", {}).get("defaults", {})
        providers = nanobot_config.get("providers", {})

        # Get default model
        default_model = defaults.get("model", "")

        # Get API config (infer from providers)
        api_key = ""
        base_url = ""
        for provider_name, provider_config in providers.items():
            if provider_config.get("api_key"):
                api_key = provider_config["api_key"]
            if provider_config.get("api_base"):
                base_url = provider_config["api_base"]

        config.inherit_from_nanobot(
            default_model=default_model,
            api_key=api_key,
            base_url=base_url,
        )

    return config
"""Ablation toggles as a first-class config object, not scattered flags --
the eval harness (task 17/18) constructs one PipelineConfig per row of the
ablation table and runs the *same* Agent code with different stages
switched on, so the table measures the pipeline, not six reimplementations
of it."""
from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineConfig:
    use_schema_retrieval: bool = True   # False: dump the full allowed schema into the prompt
    use_value_index: bool = True
    use_self_critique: bool = True
    use_repair_loop: bool = True        # False: a single generation attempt, no retry on DB error
    use_semantic_layer: bool = True     # False: exclude main_semantic tables from what the agent can see
    use_cache: bool = True
    use_ambiguity_check: bool = True
    top_k_tables: int = 4

    @staticmethod
    def single_shot_baseline() -> "PipelineConfig":
        return PipelineConfig(
            use_schema_retrieval=False, use_value_index=False, use_self_critique=False,
            use_repair_loop=False, use_semantic_layer=False, use_cache=False,
            use_ambiguity_check=False,
        )

# MSM source-value failure fixture

This deterministic fixture is copied from main at `0667e3c5ad9e05a8ea6543c14e1b33d481611638`. It derives from the captured `msm-portable` fixture by replacing pressure-level `u` values with NaN and recomputing each payload hash. It verifies that an otherwise valid portable payload with missing source values cannot replace the last successful calculation or establish latest-Run evidence. This is test data, not operational weather.

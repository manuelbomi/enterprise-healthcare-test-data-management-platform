# infra/terraform/modules

Shared Terraform modules referenced by both `../aws` and `../azure`
examples (e.g., a common tagging/naming convention module). Empty as of
Phase 0 — populated in Phase 20 alongside the first real resource
definitions, once there is enough duplication between the AWS and Azure
examples to justify factoring out a shared module.

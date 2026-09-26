# Example AWS infrastructure for the enterprise healthcare test data
# management platform's cloud dependencies.
#
# Phase 0 scope: structural placeholder only. No resources are defined
# yet — this file exists to fix the provider/backend shape so a later
# phase starts from an agreed structure. That later phase turned out to
# be Phase 12 (Kubernetes/Helm + Terraform examples), which deliberately
# built out ../azure/main.tf in full (a real, terraform validate/fmt
# clean example) while leaving this AWS example unchanged, still
# passing, as an intentional asymmetry — see `docs/problems/problems_phase_12.md` and
# `ROADMAP.md`'s Phase 12 section for that decision. This file remains
# the Phase 0 structural placeholder it always was; a future phase that
# wants an equally real AWS example should follow azure/main.tf's
# pattern (real resources per ADR-0004/0005, `terraform validate`/`fmt`
# both clean, still never applied against a real account by any CI
# workflow).
# Never apply this against a real AWS account without replacing every
# placeholder and reviewing it as you would any production change.

terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Example only: a real deployment would use a remote backend (e.g., an
  # S3 bucket + DynamoDB lock table) rather than local state. Intentionally
  # left unconfigured here so this file can never accidentally write state
  # against a real backend.
  # backend "s3" {
  #   bucket = "REPLACE_ME-tfstate-bucket"
  #   key    = "tdm-platform/terraform.tfstate"
  #   region = "REPLACE_ME"
  # }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment name (e.g., 'dev', 'qa'). Never 'prod' from this example."
  type        = string
  default     = "dev"
}

# Planned resources (added in Phase 20), documented here so the intended
# shape is clear:
#   - aws_s3_bucket.snapshots        # private, versioned, encrypted-at-rest
#   - aws_db_instance.metadata        # managed PostgreSQL for the metadata plane
#   - aws_iam_role / aws_iam_policy    # least-privilege roles per service
#   - aws_secretsmanager_secret        # backing the secrets provider adapter

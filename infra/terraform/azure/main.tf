# Example Azure infrastructure for the enterprise healthcare test data
# management platform's cloud dependencies.
#
# Phase 0 scope: structural placeholder only. No resources are defined
# yet — mirrors infra/terraform/aws/main.tf's status. Never apply this
# against a real Azure subscription without replacing every placeholder
# and reviewing it as you would any production change.

terraform {
  required_version = ">= 1.7"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.100"
    }
  }

  # Example only: a real deployment would use a remote backend (e.g., an
  # Azure Storage Account container) rather than local state. Intentionally
  # left unconfigured here.
  # backend "azurerm" {
  #   resource_group_name  = "REPLACE_ME"
  #   storage_account_name = "REPLACE_ME"
  #   container_name        = "tfstate"
  #   key                    = "tdm-platform.tfstate"
  # }
}

provider "azurerm" {
  features {}
}

variable "location" {
  description = "Azure region to deploy into."
  type        = string
  default     = "eastus"
}

variable "environment" {
  description = "Deployment environment name (e.g., 'dev', 'qa'). Never 'prod' from this example."
  type        = string
  default     = "dev"
}

# Planned resources (added in Phase 20), documented here so the intended
# shape is clear:
#   - azurerm_storage_account / azurerm_storage_container   # ADLS/Blob for snapshots
#   - azurerm_postgresql_flexible_server                     # managed PostgreSQL for the metadata plane
#   - azurerm_role_assignment                                  # least-privilege roles per service
#   - azurerm_key_vault + azurerm_key_vault_secret               # backing the secrets provider adapter

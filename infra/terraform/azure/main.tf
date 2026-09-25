# Example Azure infrastructure for the enterprise healthcare test data
# management platform's cloud dependencies.
#
# Phase 12 scope: a real, structurally valid (terraform validate/fmt
# clean — see problems_phase_12.md for the exact command run) example
# of what this platform's production deployment looks like on Azure:
# AKS for the control-plane/governance-service/frontend containers (see
# ../../k8s/helm/tdm-platform), Azure Database for PostgreSQL Flexible
# Server for the metadata plane (ADR-0004), a Storage Account
# (ADLS Gen2-enabled) for snapshot/object storage
# (docs/adr/0005-object-storage-abstraction.md), Azure Container
# Registry for the three real images this repository now builds
# (services/control-plane/Dockerfile, services/governance-service/
# Dockerfile, frontend/Dockerfile), and Key Vault backing the
# security/governance plane's secrets provider adapter
# (ARCHITECTURE.md section 2.4).
#
# `terraform apply` is never run against a real Azure subscription from
# this repository or by any CI workflow here (see
# .github/workflows/deploy-production.yml's own header comment — its
# "production" stage is a Docker Compose stand-in, not this file).
# Every name below is a placeholder; replace every `REPLACE_ME` and
# review this the way any production infrastructure change would be
# reviewed before ever pointing it at a real subscription. See
# docs/AZURE_PRODUCTION_DEPLOYMENT.md for the full narrative this file
# implements, including exactly what stays cloud-portable (per
# ADR-0005/ADR-0003) versus what is genuinely Azure-specific here.

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
  # left unconfigured here so this file can never accidentally write state
  # against a real backend.
  # backend "azurerm" {
  #   resource_group_name  = "REPLACE_ME"
  #   storage_account_name = "REPLACE_ME"
  #   container_name       = "tfstate"
  #   key                  = "tdm-platform.tfstate"
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

  validation {
    condition     = var.environment != "prod" && var.environment != "production"
    error_message = "This example is never applied as a real production environment from this repository — see this file's header comment."
  }
}

variable "project_name" {
  description = "Short name used to derive resource names. Replace before any real use."
  type        = string
  default     = "REPLACE_ME-tdm"
}

variable "postgres_admin_username" {
  description = "Administrator login for the managed PostgreSQL server. The password is never set here — see the postgres_admin_password variable below."
  type        = string
  default     = "tdmadmin"
}

variable "postgres_admin_password" {
  description = <<-EOT
    Administrator password for the managed PostgreSQL server. Deliberately
    has NO default (Terraform will prompt, or a real pipeline supplies it
    via TF_VAR_postgres_admin_password from a secret store — e.g. this
    same Key Vault, bootstrapped out-of-band, or a CI secret) — never
    committed to this repository. See SECURITY.md.
  EOT
  type        = string
  sensitive   = true
}

resource "azurerm_resource_group" "tdm" {
  name     = "${var.project_name}-${var.environment}-rg"
  location = var.location
}

# ---------------------------------------------------------------------------
# Container registry — where a real CI pipeline would push the three
# images .github/workflows/container-build.yml builds (control-plane,
# governance-service, frontend); that workflow itself never pushes
# anywhere (no registry credentials exist in this repository).
# ---------------------------------------------------------------------------
resource "azurerm_container_registry" "tdm" {
  name                = replace("${var.project_name}${var.environment}acr", "-", "")
  resource_group_name = azurerm_resource_group.tdm.name
  location            = azurerm_resource_group.tdm.location
  sku                 = "Basic"
  admin_enabled       = false
}

# ---------------------------------------------------------------------------
# AKS — runs infra/k8s/helm/tdm-platform (control-plane, governance-
# service, frontend Deployments/Services). A single, small default node
# pool — this is a teaching example, not a sized production cluster.
# ---------------------------------------------------------------------------
resource "azurerm_kubernetes_cluster" "tdm" {
  name                = "${var.project_name}-${var.environment}-aks"
  resource_group_name = azurerm_resource_group.tdm.name
  location            = azurerm_resource_group.tdm.location
  dns_prefix          = "${var.project_name}-${var.environment}"

  default_node_pool {
    name       = "system"
    node_count = 2
    vm_size    = "Standard_D2s_v5"
  }

  identity {
    type = "SystemAssigned"
  }
}

# Least-privilege role assignment: AKS's managed identity may pull
# images from the registry above, nothing more.
resource "azurerm_role_assignment" "aks_pull_from_acr" {
  scope                = azurerm_container_registry.tdm.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.tdm.kubelet_identity[0].object_id
}

# ---------------------------------------------------------------------------
# Managed PostgreSQL — the metadata plane (ADR-0004), replacing the
# Docker Compose `postgres` container / SQLite dev default
# (control_plane.config.Settings.lifecycle_database_url) in production.
# ---------------------------------------------------------------------------
resource "azurerm_postgresql_flexible_server" "tdm_metadata" {
  name                = "${var.project_name}-${var.environment}-pg"
  resource_group_name = azurerm_resource_group.tdm.name
  location            = azurerm_resource_group.tdm.location

  administrator_login    = var.postgres_admin_username
  administrator_password = var.postgres_admin_password

  sku_name   = "B_Standard_B1ms" # smallest burstable tier — a teaching example, size for real load before production use
  storage_mb = 32768
  version    = "16"

  backup_retention_days = 7
}

resource "azurerm_postgresql_flexible_server_database" "tdm_metadata_db" {
  name      = "tdm_metadata"
  server_id = azurerm_postgresql_flexible_server.tdm_metadata.id
  collation = "en_US.utf8"
  charset   = "utf8"
}

# ---------------------------------------------------------------------------
# Storage — snapshot / object storage for the data plane's masked,
# subsetted, and synthetic datasets (docs/adr/0005-object-storage-abstraction.md's
# Azure Blob/ADLS adapter target). ADLS Gen2 (hierarchical namespace) is
# enabled so this is a real Blob+ADLS-capable account, matching the
# Parquet/Delta layout data_plane.reference_data.writers already
# produces locally.
# ---------------------------------------------------------------------------
resource "azurerm_storage_account" "tdm_snapshots" {
  name                     = replace("${var.project_name}${var.environment}snap", "-", "")
  resource_group_name      = azurerm_resource_group.tdm.name
  location                 = azurerm_resource_group.tdm.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  is_hns_enabled           = true # ADLS Gen2

  blob_properties {
    versioning_enabled = true
  }
}

resource "azurerm_storage_container" "tdm_snapshots" {
  name                  = "tdm-snapshots"
  storage_account_name  = azurerm_storage_account.tdm_snapshots.name
  container_access_type = "private"
}

# ---------------------------------------------------------------------------
# Key Vault — backs the security/governance plane's secrets provider
# adapter (ARCHITECTURE.md section 2.4: "a thin interface over
# environment variables locally and a real secret manager ... in the
# cloud"). Populated out-of-band by a real deployment pipeline, never
# by this Terraform example (no secret *values* are set here).
# ---------------------------------------------------------------------------
data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "tdm" {
  name                = "${var.project_name}-${var.environment}-kv"
  resource_group_name = azurerm_resource_group.tdm.name
  location            = azurerm_resource_group.tdm.location
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"

  purge_protection_enabled = true
}

# AKS pods (via workload identity / CSI Secrets Store driver in a real
# deployment) read secrets from this vault; write access remains
# restricted to whoever/whatever manages secrets out-of-band, not the
# cluster's own identity.
resource "azurerm_role_assignment" "aks_read_secrets" {
  scope                = azurerm_key_vault.tdm.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_kubernetes_cluster.tdm.kubelet_identity[0].object_id
}

output "resource_group_name" {
  value = azurerm_resource_group.tdm.name
}

output "aks_cluster_name" {
  value = azurerm_kubernetes_cluster.tdm.name
}

output "postgres_fqdn" {
  value = azurerm_postgresql_flexible_server.tdm_metadata.fqdn
}

output "storage_account_name" {
  value = azurerm_storage_account.tdm_snapshots.name
}

output "key_vault_name" {
  value = azurerm_key_vault.tdm.name
}

output "container_registry_login_server" {
  value = azurerm_container_registry.tdm.login_server
}

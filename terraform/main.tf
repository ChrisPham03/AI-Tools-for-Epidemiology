# Stage 1: provider only. Bedrock needs no provisioned resources to call.
# Stage 3 (Textract): add a private, encrypted S3 bucket for multi-page PDFs
# and a least-privilege policy for Textract, Bedrock and that bucket.

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project = var.project
    }
  }
}

variable "region" {
  description = "AWS region; a Canadian region keeps data in Canada"
  type        = string
  default     = "ca-central-1"
}

variable "project" {
  description = "Tag applied to all resources"
  type        = string
  default     = "epi-extract"
}

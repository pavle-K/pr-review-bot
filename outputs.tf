output "webhook_url" {
  description = "GitHub webhook payload URL (Payload URL field in the repo webhook settings)"
  value       = "${aws_apigatewayv2_api.this.api_endpoint}/webhook"
}

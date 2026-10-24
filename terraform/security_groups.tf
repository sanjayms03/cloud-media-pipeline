resource "aws_security_group" "worker" {
  name        = "${local.prefix}-worker-sg"
  description = "Security group for the media-processing EC2 worker"
  vpc_id      = aws_vpc.lab.id

  # Baseline: admin access restricted to inside the VPC.
  ingress {
    description = "SSH from inside the VPC only"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr]
  }

  ingress {
    description = "Worker health endpoint, VPC-internal"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  # CMP-SEC-003: egress is wide open to every destination and protocol. A
  # tightened rule would allow 443 to the AWS prefix list only.
  egress {
    description = "Unrestricted egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.prefix}-worker-sg" })
}

# ---------------------------------------------------------------------------
# CMP-SEC-002: ingress open to the entire IPv4 internet on a non-essential
# debug port. Opt-in and OFF by default; never enable this outside an isolated
# sandbox account.
# ---------------------------------------------------------------------------
resource "aws_security_group_rule" "worker_debug_open" {
  count = var.enable_open_security_group ? 1 : 0

  type              = "ingress"
  description       = "LAB ONLY: debug port exposed to 0.0.0.0/0"
  security_group_id = aws_security_group.worker.id
  from_port         = 9229
  to_port           = 9229
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
}

resource "aws_security_group" "lambda" {
  name        = "${local.prefix}-lambda-sg"
  description = "Security group for VPC-attached Lambda functions"
  vpc_id      = aws_vpc.lab.id

  egress {
    description = "Unrestricted egress"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.prefix}-lambda-sg" })
}

resource "aws_security_group" "database" {
  name        = "${local.prefix}-db-sg"
  description = "Security group for the opt-in RDS lab instance"
  vpc_id      = aws_vpc.lab.id

  # CMP-SEC-006: the database accepts connections from the whole VPC CIDR rather
  # than only from the worker and Lambda security groups.
  ingress {
    description = "PostgreSQL from anywhere inside the VPC"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, { Name = "${local.prefix}-db-sg" })
}


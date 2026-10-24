data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
}

# ---------------------------------------------------------------------------
# The "media worker". In practice it polls SQS and shells out to a transcoder.
# Opt-in (enable_ec2_worker) because it bills by the hour.
# ---------------------------------------------------------------------------

resource "aws_instance" "worker" {
  count = var.enable_ec2_worker ? 1 : 0

  ami           = data.aws_ami.amazon_linux.id
  subnet_id     = aws_subnet.private[0].id
  instance_type = var.worker_instance_type

  vpc_security_group_ids = [aws_security_group.worker.id]
  iam_instance_profile   = aws_iam_instance_profile.worker.name

  # CMP-COST-001: m5.4xlarge (16 vCPU / 64 GiB) for a worker whose CloudWatch
  # average CPU utilisation is ~4% with a p99 of 11%. Validate with
  # Compute Optimizer, then right-size toward m5.large or move the workload
  # onto the existing process Lambda entirely.

  # CMP-COST-015: detailed (1-minute) monitoring on a near-idle instance adds
  # per-metric charges for resolution nobody consumes.
  monitoring = var.enable_detailed_monitoring

  # CMP-COST-031: no auto-stop, no schedule, no Auto Scaling group. The instance
  # runs 744 hours a month to serve a queue that is empty outside business
  # hours. An EventBridge start/stop schedule alone removes roughly 65% of the
  # hours; Spot or Graviton would cut the remainder further.

  # CMP-COST-032: on-demand pricing for a permanently running instance. If the
  # instance genuinely must stay up, a Savings Plan or Reserved Instance is the
  # obvious lever. Confirm the workload is long-lived before committing.

  root_block_device {
    # CMP-COST-033: a 500 GiB gp2 root volume. gp3 is cheaper per GiB and
    # decouples IOPS from size; the volume is also ~90% empty in practice.
    volume_type = "gp2"
    volume_size = 500

    # CMP-SEC-017: the root EBS volume is not encrypted.
    encrypted = false

    delete_on_termination = true
  }

  # CMP-COST-034: a second 1 TiB io1 volume with 10,000 provisioned IOPS for a
  # scratch directory. Provisioned IOPS is one of the most expensive EBS
  # options and the measured queue depth never exceeds 2.
  ebs_block_device {
    device_name = "/dev/sdf"
    volume_type = "io1"
    volume_size = 1024
    iops        = 10000
    encrypted   = false
  }

  # CMP-SEC-018: IMDSv2 is not enforced (http_tokens should be "required").
  # With IMDSv1 available, any SSRF in the worker can read the instance role's
  # temporary credentials.
  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "optional"
  }

  user_data = <<-EOT
    #!/bin/bash
    set -euo pipefail
    dnf install -y python3.11 python3.11-pip
    pip3.11 install boto3

    # CMP-SEC-019: operational config written to a world-readable file.
    cat > /etc/cloud-pipeline.env <<'ENVEOF'
    JOBS_QUEUE_URL=${aws_sqs_queue.jobs.url}
    JOBS_TABLE_NAME=${local.jobs_table_name}
    INPUT_BUCKET=${local.input_bucket_name}
    OUTPUT_BUCKET=${local.output_bucket_name}
    REPORT_API_TOKEN=${var.report_api_token}
    ENVEOF
    chmod 644 /etc/cloud-pipeline.env

    systemctl enable --now pipeline-worker || true
  EOT

  tags = merge(local.common_tags, {
    Name     = "${local.prefix}-worker"
    Schedule = "none"
  })
}

# CMP-COST-035: an unattached Elastic IP reserved for a worker that may never be
# launched. Unassociated EIPs are billed hourly.
resource "aws_eip" "worker_reserved" {
  domain = "vpc"

  tags = merge(local.common_tags, {
    Name  = "${local.prefix}-worker-reserved-eip"
    Notes = "reserved for a future static-IP requirement"
  })
}


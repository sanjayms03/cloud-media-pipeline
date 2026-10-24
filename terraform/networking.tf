# ---------------------------------------------------------------------------
# Networking. Two public subnets and two private subnets across two AZs.
# The cross-AZ layout is what makes CMP-COST-013 (data transfer) reachable.
# ---------------------------------------------------------------------------

resource "aws_vpc" "lab" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(local.common_tags, { Name = "${local.prefix}-vpc" })
}

resource "aws_internet_gateway" "lab" {
  vpc_id = aws_vpc.lab.id

  tags = merge(local.common_tags, { Name = "${local.prefix}-igw" })
}

resource "aws_subnet" "public" {
  count = 2

  vpc_id                  = aws_vpc.lab.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true

  tags = merge(local.common_tags, {
    Name = "${local.prefix}-public-${count.index}"
    Tier = "public"
  })
}

resource "aws_subnet" "private" {
  count = 2

  vpc_id            = aws_vpc.lab.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  availability_zone = local.azs[count.index]

  tags = merge(local.common_tags, {
    Name = "${local.prefix}-private-${count.index}"
    Tier = "private"
  })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.lab.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.lab.id
  }

  tags = merge(local.common_tags, { Name = "${local.prefix}-public-rt" })
}

resource "aws_route_table_association" "public" {
  count = 2

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# ---------------------------------------------------------------------------
# CMP-COST-002: NAT Gateway. Opt-in because it bills per hour AND per GB.
# A single NAT in one AZ also forces cross-AZ traffic from the other AZ's
# private subnet, compounding CMP-COST-013.
# ---------------------------------------------------------------------------

resource "aws_eip" "nat" {
  count = var.enable_nat_gateway ? 1 : 0

  domain = "vpc"

  tags = merge(local.common_tags, { Name = "${local.prefix}-nat-eip" })
}

resource "aws_nat_gateway" "lab" {
  count = var.enable_nat_gateway ? 1 : 0

  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id

  tags = merge(local.common_tags, { Name = "${local.prefix}-nat" })

  depends_on = [aws_internet_gateway.lab]
}

resource "aws_route_table" "private" {
  count = 2

  vpc_id = aws_vpc.lab.id

  tags = merge(local.common_tags, { Name = "${local.prefix}-private-rt-${count.index}" })
}

resource "aws_route" "private_nat" {
  count = var.enable_nat_gateway ? 2 : 0

  route_table_id         = aws_route_table.private[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.lab[0].id
}

resource "aws_route_table_association" "private" {
  count = 2

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# ---------------------------------------------------------------------------
# CMP-COST-016: no S3 or DynamoDB VPC gateway endpoints. Gateway endpoints are
# free and would keep S3/DynamoDB traffic off the NAT Gateway entirely. Without
# them every byte the EC2 worker reads from S3 is billed as NAT data processing.
#
# The fix is roughly:
#   resource "aws_vpc_endpoint" "s3" {
#     vpc_id            = aws_vpc.lab.id
#     service_name      = "com.amazonaws.${var.aws_region}.s3"
#     vpc_endpoint_type = "Gateway"
#     route_table_ids   = aws_route_table.private[*].id
#   }
# ---------------------------------------------------------------------------

# CMP-SEC-011: VPC flow logs are not enabled, so there is no network audit trail.


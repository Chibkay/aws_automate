#!/bin/bash

# Get a list of all regions
regions=$(aws ec2 describe-regions --query 'Regions[*].RegionName' --output text)

# Loop through each region
for region in $regions; do
    echo "Checking region: $region"
    
    # Set the current region
    export AWS_DEFAULT_REGION=$region
    
    # Get a list of all security group IDs
    group_ids=$(aws ec2 describe-security-groups --query 'SecurityGroups[*].GroupId' --output text)
    
    # Loop through each security group
    for group_id in $group_ids; do
        # Check ingress rules for port 22
        allow_ssh=$(aws ec2 describe-security-groups --group-ids $group_id --query 'SecurityGroups[0].IpPermissions[?ToPort==`22` && contains(IpRanges[].CidrIp, `0.0.0.0/0`) == `true`]' --output text)
        
        # Check ingress rules for port 3389
        allow_rdp=$(aws ec2 describe-security-groups --group-ids $group_id --query 'SecurityGroups[0].IpPermissions[?ToPort==`3389` && contains(IpRanges[].CidrIp, `0.0.0.0/0`) == `true`]' --output text)
        
        # Output any violations
        if [ -n "$allow_ssh" ]; then
            echo "  Security Group $group_id allows SSH (port 22) access from 0.0.0.0/0"
        fi
        
        if [ -n "$allow_rdp" ]; then
            echo "  Security Group $group_id allows RDP (port 3389) access from 0.0.0.0/0"
        fi
    done
    
    # Get a list of all network ACL IDs
    acl_ids=$(aws ec2 describe-network-acls --query 'NetworkAcls[*].NetworkAclId' --output text)
    
    # Loop through each network ACL
    for acl_id in $acl_ids; do
        # Check for inbound rules allowing traffic from 0.0.0.0/0 on port 22 or 3389
        allow_ssh=$(aws ec2 describe-network-acls --output text --network-acl-ids $acl_id --query 'NetworkAcls[*].Entries[?(RuleAction==`allow` && Egress==`false`)].{RN:RuleNumber}')
        allow_rdp=$(aws ec2 describe-network-acls --output text --network-acl-ids $acl_id --query 'NetworkAcls[*].Entries[?(RuleAction==`allow` && Egress==`false`)].{RN:RuleNumber}')
        
        # Output any violations
        if [ -n "$allow_ssh" ]; then
            echo "  Network ACL $acl_id allows SSH (port 22) access from 0.0.0.0/0"
        fi
        
        if [ -n "$allow_rdp" ]; then
            echo "  Network ACL $acl_id allows RDP (port 3389) access from 0.0.0.0/0"
        fi
    done
    
    echo ""
done


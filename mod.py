import boto3
import subprocess
import yaml
import time

# Initialize the EC2 and Kubectl clients
ec2_client = boto3.client('ec2')
kubectl_command = 'kubectl'

# Step 1: Get a list of all nodes in the Kubernetes cluster
node_output = subprocess.check_output([kubectl_command, 'get', 'nodes', '-o', 'json'])
nodes = yaml.safe_load(node_output)['items']

# Step 2: Iterate over each node
for node in nodes:
    node_name = node['metadata']['name']
    print(f"Checking node: {node_name}")
    
    # Step 3: Get the internal IP address of the node
    internal_ip = node['status']['addresses'][0]['address']
    print(f"Internal IP for node {node_name}: {internal_ip}")
    
    # Step 4: Get the instance ID associated with the internal IP address
    instance_id = None
    instance_metadata = ec2_client.describe_instances(Filters=[{'Name': 'private-ip-address', 'Values': [internal_ip]}])
    print("Instance metadata:", instance_metadata)
    if instance_metadata['Reservations']:
        instance_id = instance_metadata['Reservations'][0]['Instances'][0]['InstanceId']
    
    # Check if instance_id is defined
    if instance_id:
        print(f"Instance ID for node {node_name}: {instance_id}")

        
        # Step 5: Get the volume ID from the instance
        volumes_response = ec2_client.describe_volumes(Filters=[{'Name': 'attachment.instance-id', 'Values': [instance_id]}])
        volumes = volumes_response['Volumes']
        if volumes:
            volume_id = volumes[0]['VolumeId']
            print(f"Volume ID for instance {instance_id}: {volume_id}")

            # Step 6: Check if EBS volume is encrypted
            response = ec2_client.describe_volumes(VolumeIds=[volume_id])
            print("Volume response:", response)
            encryption_status = response['Volumes'][0]['Encrypted']
            print(f"Encryption status for volume {volume_id}: {encryption_status}")

            if not encryption_status:
                # Step 7: Check if snapshot already exists
                snapshots = ec2_client.describe_snapshots(Filters=[{'Name': 'volume-id', 'Values': [volume_id]}])['Snapshots']
                print(f"Snapshots for volume {volume_id}: {snapshots}")
                if not snapshots:  # If no snapshots exist, create a new one
                    snapshot_response = ec2_client.create_snapshot(VolumeId=volume_id)
                    snapshot_id = snapshot_response['SnapshotId']
                    print(f"Snapshot ID for volume {volume_id}: {snapshot_id}")
                else:  # If snapshot exists, use the existing snapshot ID
                    snapshot_id = snapshots[0]['SnapshotId']
                
                # Step 8: Copy and encrypt the snapshot (if necessary)
                if not snapshots or not snapshots[0]['Encrypted']:  # Check if snapshot needs to be encrypted
                    source_region = 'eu-north-1'  # Modify this with the appropriate source region
                    print("Copying snapshot...")
                    copy_response = ec2_client.copy_snapshot(SourceSnapshotId=snapshot_id, Encrypted=True, SourceRegion=source_region)
                    encrypted_snapshot_id = copy_response['SnapshotId']
                    print(f"Encrypted snapshot ID for volume {volume_id}: {encrypted_snapshot_id}")

                    # Wait for the snapshot to become available
                    while True:
                        snapshot_response = ec2_client.describe_snapshots(SnapshotIds=[encrypted_snapshot_id])
                        snapshot_state = snapshot_response['Snapshots'][0]['State']
                        print(f"Snapshot state for snapshot {encrypted_snapshot_id}: {snapshot_state}")
                        if snapshot_state == 'completed':
                            break
                        elif snapshot_state == 'error':
                            raise Exception("Snapshot creation failed.")
                        time.sleep(10)  # Wait for 10 seconds before checking again

                    snapshot_id = encrypted_snapshot_id

                # Step 9: Create a volume from the snapshot
                encrypted_volume_response = ec2_client.create_volume(SnapshotId=snapshot_id, AvailabilityZone='eu-north-1a')
                encrypted_volume_id = encrypted_volume_response['VolumeId']
                print(f"Encrypted volume ID for volume {volume_id}: {encrypted_volume_id}")

                # Wait for the volume to become available
                while True:
                    volume_state = ec2_client.describe_volumes(VolumeIds=[encrypted_volume_id])['Volumes'][0]['State']
                    print(f"Volume state for volume {encrypted_volume_id}: {volume_state}")
                    if volume_state == 'available':
                        break
                    time.sleep(10)  # Wait for 10 seconds before checking again

                # Step 10: Attach the new encrypted volume to the instance if /dev/sdf is not already in use
                attachments = ec2_client.describe_instances(InstanceIds=[instance_id])['Reservations'][0]['Instances'][0]['BlockDeviceMappings']
                sdf_in_use = any(attachment['DeviceName'] == '/dev/sdf' for attachment in attachments)
                if not sdf_in_use:
                    ec2_client.attach_volume(VolumeId=encrypted_volume_id, InstanceId=instance_id, Device='/dev/sdf')
                else:
                    print("Device /dev/sdf is already in use. Skipping attachment.")

                existing_pv_yaml = subprocess.check_output([kubectl_command, 'get', 'pv', 'mymanual-pv', '-o', 'yaml']).decode('utf-8')
                existing_pvc_yaml = subprocess.check_output([kubectl_command, 'get', 'pvc', 'www-nginx-0', '-o', 'yaml']).decode('utf-8')

                with open("existing_pv.yaml", "w") as pv_file:
                    pv_file.write(existing_pv_yaml)

                with open("existing_pvc.yaml", "w") as pvc_file:
                    pvc_file.write(existing_pvc_yaml)
                
                # Step 11: Delete existing PV and PVC
                subprocess.run([kubectl_command, 'delete', 'pv', 'mymanual-pv'], check=True)
                subprocess.run([kubectl_command, 'delete', 'pvc', 'www-nginx-0'], check=True)

                # Step 12: Modify exported PV and PVC to attach encrypted volume
                existing_pv_data = yaml.safe_load(existing_pv_yaml)
                existing_pv_data['spec']['awsElasticBlockStore']['volumeID'] = encrypted_volume_id
                modified_pv_yaml = yaml.dump(existing_pv_data)

                existing_pvc_data = yaml.safe_load(existing_pvc_yaml)
                existing_pvc_data['spec']['volumeName'] = existing_pv_data['metadata']['name']
                modified_pvc_yaml = yaml.dump(existing_pvc_data)

                with open("existing_pv.yaml", "w") as pv_file:
                    pv_file.write(modified_pv_yaml)

                with open("existing_pvc.yaml", "w") as pvc_file:
                    pvc_file.write(modified_pvc_yaml)

                # Step 13: Create PV and PVC
                subprocess.run([kubectl_command, 'apply', '-f', 'existing_pv.yaml'], check=True)
                subprocess.run([kubectl_command, 'apply', '-f', 'existing_pvc.yaml'], check=True)

                # Step 14: Scale up the application
                subprocess.run([kubectl_command, 'scale', 'sts', 'nginx', '--replicas', '1'], check=True)
        else:
            print(f"No volumes found for instance {instance_id}")
    else:
        print(f"No instance ID found for node: {node_name}")


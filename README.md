These scripts helps automate AWS tasks.
The check script checks:
* All security groups and NACL in all regions
* Confirming if ssh and rdp are open to 0.0.0.0/0


Mod script checks:
* if a pv is encrypted, if it is not, creates a snapshot from the unencrypted pv
*  encrypt the snapshot
*  make a volume out of the snapshot
*  attach the volume to the ec2 instance
*  scale down the application
*  modify the existing pv to use the encrytped volume
*  scale up the application

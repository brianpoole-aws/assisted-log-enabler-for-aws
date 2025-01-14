#// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#// SPDX-License-Identifier: Apache-2.0
# Assisted Log Enabler for AWS - Find resources that are not logging, and turn them on.
# Joshua "DozerCat" McKiddy - Customer Incident Response Team (CIRT) - AWS


import logging
import os
import json
import boto3
import time
import datetime
import argparse
import csv
import string
import random
from botocore.exceptions import ClientError
from datetime import timezone

current_date = datetime.datetime.now(tz=timezone.utc)
current_date_string = str(current_date)
timestamp_date = datetime.datetime.now(tz=timezone.utc).strftime("%Y-%m-%d-%H%M%S")
timestamp_date_string = str(timestamp_date)


sts = boto3.client('sts')
s3 = boto3.client('s3')
cloudtrail = boto3.client('cloudtrail')
organizations = boto3.client('organizations')
region = os.environ['AWS_REGION']


region_list = ['af-south-1', 'ap-east-1', 'ap-south-1', 'ap-northeast-1', 'ap-northeast-2', 'ap-northeast-3', 'ap-southeast-1', 'ap-southeast-2', 'ca-central-1', 'eu-central-1', 'eu-west-1', 'eu-west-2', 'eu-west-3', 'eu-north-1', 'eu-south-1', 'me-south-1', 'sa-east-1', 'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2']


# 0. Define random string for S3 Bucket Name
def random_string_generator():
    lower_letters = string.ascii_lowercase
    numbers = string.digits
    unique_end = (''.join(random.choice(lower_letters + numbers) for char in range(6)))
    return unique_end


# 1. Obtain the AWS Accounts inside of AWS Organizations
def org_account_grab():
    """Function to list accounts inside of AWS Organizations"""
    try:
        OrgAccountIdList: list = []
        org_account_list = organizations.list_accounts()
        for accounts in org_account_list['Accounts']:
            OrgAccountIdList.append(accounts['Id'])
        get_organization_id = organizations.describe_organization()
        organization_id = get_organization_id['Organization']['Id']
    except Exception as exception_handle:
        logging.error(exception_handle)
        logging.error("Multi account mode is only for accounts using AWS Organizations.")
        logging.error("Please run the Assisted Log Enabler in single account mode to turn on AWS Logs.")
        exit()
    return OrgAccountIdList, organization_id


# 2. Obtain the current AWS Account Number
def get_account_number():
    """Function to grab AWS Account number that Assisted Log Enabler runs from."""
    sts = boto3.client('sts')
    account_number = sts.get_caller_identity()["Account"]
    return account_number


# 3. Create a Bucket and Lifecycle Policy
def create_bucket(organization_id, account_number, unique_end):
    """Function to create the bucket for storing logs"""
    try:
        logging.info("Creating bucket in %s" % account_number)
        logging.info("CreateBucket API Call")
        if region == 'us-east-1':
            logging_bucket_dict = s3.create_bucket(
                Bucket="aws-log-collection-" + account_number + "-" + region + "-" + unique_end
            )
        else:
            logging_bucket_dict = s3.create_bucket(
                Bucket="aws-log-collection-" + account_number + "-" + region + "-" + unique_end,
                CreateBucketConfiguration={
                    'LocationConstraint': region
                }
            )
        logging.info("Bucket Created.")
        logging.info("Setting lifecycle policy.")
        lifecycle_policy = s3.put_bucket_lifecycle_configuration(
            Bucket="aws-log-collection-" + account_number + "-" + region + "-" + unique_end,
            LifecycleConfiguration={
                'Rules': [
                    {
                        'Expiration': {
                            'Days': 365
                        },
                        'Status': 'Enabled',
                        'Prefix': '',
                        'ID': 'LogStorage',
                        'Transitions': [
                            {
                                'Days': 90,
                                'StorageClass': 'INTELLIGENT_TIERING'
                            }
                        ]
                    }
                ]
            }
        )
        logging.info("Lifecycle Policy successfully set.")
        create_ct_path = s3.put_object(
            Bucket="aws-log-collection-" + account_number + "-" + region + "-" + unique_end,
            Key='cloudtrail/AWSLogs/' + account_number + '/')
        create_ct_path_vpc = s3.put_object(
            Bucket="aws-log-collection-" + account_number + "-" + region + "-" + unique_end,
            Key='vpcflowlogs/')
        create_ct_path_r53 = s3.put_object(
            Bucket="aws-log-collection-" + account_number + "-" + region + "-" + unique_end,
            Key='r53querylogs/')
        bucket_policy = s3.put_bucket_policy(
            Bucket="aws-log-collection-" + account_number + "-" + region + "-" + unique_end,
            Policy='{"Version": "2012-10-17", "Statement": [{"Sid": "AWSCloudTrailAclCheck20150319","Effect": "Allow","Principal": {"Service": "cloudtrail.amazonaws.com"},"Action": "s3:GetBucketAcl","Resource": "arn:aws:s3:::aws-log-collection-' + account_number + '-' + region + '-' + unique_end + '"},{"Sid": "AWSCloudTrailWrite20150319","Effect": "Allow","Principal": {"Service": "cloudtrail.amazonaws.com"},"Action": "s3:PutObject","Resource": "arn:aws:s3:::aws-log-collection-' + account_number + '-' + region + '-' + unique_end + '/cloudtrail/AWSLogs/' + account_number + '/*","Condition": {"StringEquals": {"s3:x-amz-acl": "bucket-owner-full-control"}}},{"Sid": "AWSLogDeliveryAclCheck","Effect": "Allow","Principal": {"Service": "delivery.logs.amazonaws.com"},"Action": "s3:GetBucketAcl","Resource": "arn:aws:s3:::aws-log-collection-' + account_number + '-' + region + '-' + unique_end + '"},{"Sid": "AWSLogDeliveryWriteVPC","Effect": "Allow","Principal": {"Service": "delivery.logs.amazonaws.com"},"Action": "s3:PutObject","Resource": "arn:aws:s3:::aws-log-collection-' + account_number + '-' + region + '-' + unique_end + '/vpcflowlogs/*","Condition": {"StringEquals": {"s3:x-amz-acl": "bucket-owner-full-control"}}},{"Sid": "AWSLogDeliveryWriteR53","Effect": "Allow","Principal": {"Service": "delivery.logs.amazonaws.com"},"Action": "s3:PutObject","Resource": "arn:aws:s3:::aws-log-collection-' + account_number + '-' + region + '-' + unique_end + '/r53querylogs/*","Condition": {"StringEquals": {"s3:x-amz-acl": "bucket-owner-full-control"}}}]}'
        )
        logging.info("Setting the S3 bucket Public Access to Blocked")
        logging.info("PutPublicAccessBlock API Call")
        bucket_private = s3.put_public_access_block(
            Bucket="aws-log-collection-" + account_number + "-" + region + "-" + unique_end,
            PublicAccessBlockConfiguration={
                'BlockPublicAcls': True,
                'IgnorePublicAcls': True,
                'BlockPublicPolicy': True,
                'RestrictPublicBuckets': True
            },
        )
    except Exception as exception_handle:
        logging.error(exception_handle)
    return account_number


# 4. Find VPCs and turn flow logs on if not on already.
def flow_log_activator(account_number, OrgAccountIdList, region_list, unique_end):
    """Function to define the list of VPCs without logging turned on"""
    logging.info("Creating a list of VPCs without Flow Logs on.")
    for org_account in OrgAccountIdList:
        for aws_region in region_list:
            sts = boto3.client('sts')
            RoleArn = 'arn:aws:iam::%s:role/Assisted_Log_Enabler_IAM_Role' % org_account
            logging.info('Assuming Target Role %s for Assisted Log Enabler...' % RoleArn)
            assisted_log_enabler_sts = sts.assume_role(
                RoleArn=RoleArn,
                RoleSessionName='assisted-log-enabler-activation',
                DurationSeconds=3600,
            )
            ec2_ma = boto3.client(
            'ec2',
            aws_access_key_id=assisted_log_enabler_sts['Credentials']['AccessKeyId'],
            aws_secret_access_key=assisted_log_enabler_sts['Credentials']['SecretAccessKey'],
            aws_session_token=assisted_log_enabler_sts['Credentials']['SessionToken'],
            region_name=aws_region
            )
            logging.info("Creating a list of VPCs without Flow Logs on in region " + aws_region + ".")
            try:
                VPCList: list = []
                FlowLogList: list = []
                logging.info("DescribeVpcs API Call")
                vpcs = ec2_ma.describe_vpcs()
                for vpc_id in vpcs["Vpcs"]:
                    VPCList.append(vpc_id["VpcId"])
                logging.info("List of VPCs found within account " + org_account + ", region " + aws_region + ":")
                print(VPCList)
                vpcflowloglist = ec2_ma.describe_flow_logs()
                logging.info("DescribeFlowLogs API Call")
                for resource_id in vpcflowloglist["FlowLogs"]:
                    FlowLogList.append(resource_id["ResourceId"])
                working_list = (list(set(VPCList) - set(FlowLogList)))
                logging.info("List of VPCs found within account " + org_account + ", region " + aws_region + " WITHOUT VPC Flow Logs:")
                print(working_list)
                for no_logs in working_list:
                    logging.info(no_logs + " does not have VPC Flow logging on. It will be turned on within this function.")
                logging.info("Activating logs for VPCs that do not have them turned on.")
                logging.info("If all VPCs have Flow Logs turned on, you will get an MissingParameter error. That is normal.")
                logging.info("CreateFlowLogs API Call")
                flow_log_on =  ec2_ma.create_flow_logs(
                    ResourceIds=working_list,
                    ResourceType='VPC',
                    TrafficType='ALL',
                    LogDestinationType='s3',
                    LogDestination='arn:aws:s3:::aws-log-collection-' + account_number + '-' + region + '-' + unique_end + '/vpcflowlogs',
                    LogFormat='${version} ${account-id} ${interface-id} ${srcaddr} ${dstaddr} ${srcport} ${dstport} ${protocol} ${packets} ${bytes} ${start} ${end} ${action} ${log-status} ${vpc-id} ${subnet-id} ${instance-id} ${tcp-flags} ${type} ${pkt-srcaddr} ${pkt-dstaddr} ${region} ${az-id} ${sublocation-type} ${sublocation-id} ${pkt-src-aws-service} ${pkt-dst-aws-service} ${flow-direction} ${traffic-path}'
                )
                # Custom format specified in same order as documentation lists them at https://docs.aws.amazon.com/vpc/latest/userguide/flow-logs.html
                logging.info("VPC Flow Logs are turned on for account " + org_account + ".")
            except Exception as exception_handle:
                logging.error(exception_handle)


# 5. Turn on EKS audit and authenticator logs.
def eks_logging(region_list, OrgAccountIdList):
    """Function to turn on logging for EKS Clusters"""
    for org_account in OrgAccountIdList:
        for aws_region in region_list:
            logging.info("Turning on audit and authenticator logging for EKS clusters in AWS account " + org_account + ", in region " + aws_region + ".")
            sts = boto3.client('sts')
            RoleArn = 'arn:aws:iam::%s:role/Assisted_Log_Enabler_IAM_Role' % org_account
            logging.info('Assuming Target Role %s for Assisted Log Enabler...' % RoleArn)
            assisted_log_enabler_sts = sts.assume_role(
                RoleArn=RoleArn,
                RoleSessionName='assisted-log-enabler-activation',
                DurationSeconds=3600,
            )
            eks_ma = boto3.client(
            'eks',
            aws_access_key_id=assisted_log_enabler_sts['Credentials']['AccessKeyId'],
            aws_secret_access_key=assisted_log_enabler_sts['Credentials']['SecretAccessKey'],
            aws_session_token=assisted_log_enabler_sts['Credentials']['SessionToken'],
            region_name=aws_region
            )
            try:
                logging.info("ListClusters API Call")
                eks_clusters = eks_ma.list_clusters()
                eks_cluster_list = eks_clusters ['clusters']
                logging.info("EKS Clusters found in " + aws_region + ":")
                print(eks_cluster_list)
                for cluster in eks_cluster_list:
                    logging.info("UpdateClusterConfig API Call")
                    eks_activate = eks_ma.update_cluster_config(
                        name=cluster,
                        logging={
                            'clusterLogging': [
                                {
                                    'types': [
                                        'audit',
                                    ],
                                    'enabled': True
                                },
                                {
                                    'types': [
                                        'authenticator',
                                    ],
                                    'enabled': True
                                },
                            ]
                        }
                    )
                    if eks_activate['update']['status'] == 'InProgress':
                        logging.info(cluster + " EKS Cluster is currently updating. Status: InProgress")
                    elif eks_activate['update']['status'] == 'Failed':
                        logging.info(cluster + " EKS Cluster failed to turn on logs. Please check if you have permissions to update the logging configuration of EKS. Status: Failed")
                    elif eks_activate['update']['status'] == 'Cancelled':
                        logging.info(cluster + " EKS Cluster log update was cancelled. Status: Cancelled.")
                    else:
                        logging.info(cluster + " EKS Cluster has audit and authenticator logs turned on.")
            except Exception as exception_handle:
                logging.error(exception_handle)


# 6. Turn on Route 53 Query Logging.
def route_53_query_logs(region_list, account_number, OrgAccountIdList, unique_end):
    """Function to turn on Route 53 Query Logs for VPCs"""
    for org_account in OrgAccountIdList:
        for aws_region in region_list:
            logging.info("Turning on Route 53 Query Logging on in AWS Account " + org_account + " VPCs, in region " + aws_region + ".")
            sts = boto3.client('sts')
            RoleArn = 'arn:aws:iam::%s:role/Assisted_Log_Enabler_IAM_Role' % org_account
            logging.info('Assuming Target Role %s for Assisted Log Enabler...' % RoleArn)
            assisted_log_enabler_sts = sts.assume_role(
                RoleArn=RoleArn,
                RoleSessionName='assisted-log-enabler-activation',
                DurationSeconds=3600,
            )
            ec2_ma = boto3.client(
            'ec2',
            aws_access_key_id=assisted_log_enabler_sts['Credentials']['AccessKeyId'],
            aws_secret_access_key=assisted_log_enabler_sts['Credentials']['SecretAccessKey'],
            aws_session_token=assisted_log_enabler_sts['Credentials']['SessionToken'],
            region_name=aws_region
            )
            route53resolver_ma = boto3.client(
            'route53resolver',
            aws_access_key_id=assisted_log_enabler_sts['Credentials']['AccessKeyId'],
            aws_secret_access_key=assisted_log_enabler_sts['Credentials']['SecretAccessKey'],
            aws_session_token=assisted_log_enabler_sts['Credentials']['SessionToken'],
            region_name=aws_region
            )
            try:
                VPCList: list = []
                QueryLogList: list = []
                logging.info("DescribeVpcs API Call")
                vpcs = ec2_ma.describe_vpcs()
                for vpc_id in vpcs["Vpcs"]:
                    VPCList.append(vpc_id["VpcId"])
                logging.info("List of VPCs found within account " + org_account + ", region " + aws_region + ":")
                print(VPCList)
                logging.info("ListResolverQueryLogConfigAssociations API Call")
                query_log_details = route53resolver_ma.list_resolver_query_log_config_associations()
                for query_log_vpc_id in query_log_details['ResolverQueryLogConfigAssociations']:
                    QueryLogList.append(query_log_vpc_id['ResourceId'])
                r53_working_list = (list(set(VPCList) - set(QueryLogList)))
                logging.info("List of VPCs found within account " + org_account + ", region " + aws_region + " WITHOUT Route 53 Query Logs:")
                print(r53_working_list)
                for no_query_logs in r53_working_list:
                    logging.info(no_query_logs + " does not have Route 53 Query logging on. It will be turned on within this function.")
                logging.info("Activating logs for VPCs that do not have Route 53 Query logging turned on.")
                logging.info("CreateResolverQueryLogConfig API Call")
                create_query_log = route53resolver_ma.create_resolver_query_log_config(
                    Name='Assisted_Log_Enabler_Query_Logs_' + aws_region,
                    DestinationArn='arn:aws:s3:::aws-log-collection-' + account_number + '-' + region + '-' + unique_end + '/r53querylogs',
                    CreatorRequestId=timestamp_date_string,
                    Tags=[
                        {
                            'Key': 'Workflow',
                            'Value': 'assisted-log-enabler'
                        },
                    ]
                )
                r53_query_log_id = create_query_log['ResolverQueryLogConfig']['Id']
                logging.info("Route 53 Query Logging Created. Resource ID:" + r53_query_log_id)
                for vpc in r53_working_list:
                    logging.info("Associating " + vpc + " with the created Route 53 Query Logging.")
                    logging.info("AssocateResolverQueryLogConfig")
                    activate_r5_logs = route53resolver_ma.associate_resolver_query_log_config(
                        ResolverQueryLogConfigId=r53_query_log_id,
                        ResourceId=vpc
                    )
            except Exception as exception_handle:
                logging.error(exception_handle)


# 7. Turn on S3 Logging.
def s3_logs(region_list, account_number, OrgAccountIdList, unique_end):
    """Function to turn on Bucket Logs for Buckets"""
    for org_account in OrgAccountIdList:
        for aws_region in region_list:
            logging.info("Turning on Bucket Logging on in AWS Account " + org_account + " Buckets, in region " + aws_region + ".")
            sts = boto3.client('sts')
            RoleArn = 'arn:aws:iam::%s:role/Assisted_Log_Enabler_IAM_Role' % org_account
            logging.info('Assuming Target Role %s for Assisted Log Enabler...' % RoleArn)
            assisted_log_enabler_sts = sts.assume_role(
                RoleArn=RoleArn,
                RoleSessionName='assisted-log-enabler-activation',
                DurationSeconds=3600,
            )
            s3_ma = boto3.client(
            's3',
            aws_access_key_id=assisted_log_enabler_sts['Credentials']['AccessKeyId'],
            aws_secret_access_key=assisted_log_enabler_sts['Credentials']['SecretAccessKey'],
            aws_session_token=assisted_log_enabler_sts['Credentials']['SessionToken'],
            region_name=aws_region
            )
            try:
                S3List: list = []
                S3LogList: list = []
                logging.info("ListBuckets API Call")
                buckets = s3_ma.list_buckets()
                for bucket in buckets['Buckets']:
                    s3region=s3_ma.get_bucket_location(Bucket=bucket["Name"])['LocationConstraint']
                    if s3region == aws_region:
                        S3List.append(bucket["Name"])
                    elif s3region is None and aws_region == 'us-east-1':
                        S3List.append(bucket["Name"])
                if S3List != []:
                    logging.info("List of Buckets found within account " + org_account + ", region " + aws_region + ":")
                    print(S3List)
                    logging.info("Parsed out buckets created by Assisted Log Enabler for AWS in " + aws_region)
                    logging.info("Checking remaining buckets to see if logs were enabled by Assisted Log Enabler for AWS in " + aws_region)
                    logging.info("GetBucketLogging API Call")
                    for bucket in S3List:
                        if 'aws-s3-log-collection-' + org_account + '-' + aws_region not in str(bucket):
                            s3temp=s3_ma.get_bucket_logging(Bucket=bucket)
                            if 'TargetBucket' not in str(s3temp):
                                S3LogList.append(bucket)
                    if S3LogList != []:
                        logging.info("List of Buckets found within account " + org_account + ", region " + aws_region + " WITHOUT S3 Bucket Logs:")
                        print(S3LogList)
                        for bucket in S3LogList:
                            logging.info(bucket + " does not have S3 BUCKET logging on. It will be turned on within this function.")
                        logging.info("Creating S3 Logging Bucket")
                        """Function to create the bucket for storing logs"""
                        account_number = sts.get_caller_identity()["Account"]
                        logging.info("Creating bucket in %s" % org_account)
                        logging.info("CreateBucket API Call")
                        if aws_region == 'us-east-1':
                            logging_bucket_dict = s3_ma.create_bucket(
                                Bucket="aws-s3-log-collection-" + org_account + "-" + aws_region + "-" + unique_end
                            )
                        else:
                            logging_bucket_dict = s3_ma.create_bucket(
                                Bucket="aws-s3-log-collection-" + org_account + "-" + aws_region + "-" + unique_end,
                                CreateBucketConfiguration={
                                    'LocationConstraint': aws_region
                                }
                            )
                        logging.info("Bucket " + "aws-s3-log-collection-" + org_account + "-" + aws_region + "-" + unique_end + " Created.")
                        logging.info("Setting lifecycle policy.")
                        logging.info("PutBucketLifecycleConfiguration API Call")
                        lifecycle_policy = s3_ma.put_bucket_lifecycle_configuration(
                            Bucket="aws-s3-log-collection-" + org_account + "-" + aws_region + "-" + unique_end,
                            LifecycleConfiguration={
                                'Rules': [
                                    {
                                        'Expiration': {
                                            'Days': 365
                                        },
                                        'Status': 'Enabled',
                                        'Prefix': '',
                                        'ID': 'LogStorage',
                                        'Transitions': [
                                            {
                                                'Days': 90,
                                                'StorageClass': 'INTELLIGENT_TIERING'
                                            }
                                        ]
                                    }
                                ]
                            }
                        )
                        logging.info("Lifecycle Policy successfully set.")
                        logging.info("Setting the S3 bucket Public Access to Blocked")
                        logging.info("PutPublicAccessBlock API Call")
                        bucket_private = s3_ma.put_public_access_block(
                            Bucket="aws-s3-log-collection-" + org_account + "-" + aws_region + "-" + unique_end,
                            PublicAccessBlockConfiguration={
                                'BlockPublicAcls': True,
                                'IgnorePublicAcls': True,
                                'BlockPublicPolicy': True,
                                'RestrictPublicBuckets': True
                            },
                        )
                        logging.info("GetBucketAcl API Call")
                        id=s3_ma.get_bucket_acl(Bucket="aws-s3-log-collection-" + org_account + "-" + aws_region + "-" + unique_end)['Owner']['ID']
                        logging.info("PutBucketAcl API Call")
                        s3_ma.put_bucket_acl(Bucket="aws-s3-log-collection-" + org_account + "-" + aws_region + "-" + unique_end,GrantReadACP='uri=http://acs.amazonaws.com/groups/s3/LogDelivery',GrantWrite='uri=http://acs.amazonaws.com/groups/s3/LogDelivery',GrantFullControl='id=' + id)
                        for bucket in S3LogList:
                            logging.info("Activating logs for S3 Bucket " + bucket)
                            logging.info("PutBucketLogging API Call")
                            create_s3_log = s3_ma.put_bucket_logging(
                                Bucket=bucket,
                                BucketLoggingStatus={
                                    'LoggingEnabled': {
                                        'TargetBucket': 'aws-s3-log-collection-' + org_account + '-' + aws_region + '-' + unique_end,
                                        'TargetGrants': [
                                            {
                                                'Permission': 'FULL_CONTROL',
                                                'Grantee': {
                                                    'Type': 'Group',
                                                    'URI': 'http://acs.amazonaws.com/groups/s3/LogDelivery'
                                                },
                                            },
                                        ],
                                        'TargetPrefix': 's3logs/' + bucket
                                    }
                                }
                            )
                    else:
                        logging.info("No S3 Bucket WITHOUT Logging enabled on account " + org_account + " region " + aws_region)
                else: 
                    logging.info("No S3 Buckets found within account " + org_account + ", region " + aws_region + ":")
            except Exception as exception_handle:
                logging.error(exception_handle)


# 8. Turn on LB Logging.
def lb_logs(region_list, account_number, OrgAccountIdList, unique_end):
    """Function to turn on Load Balancer Logs"""
    for org_account in OrgAccountIdList:
        for aws_region in region_list:
            logging.info("Checking for Load Balancer Logging in the account "  + org_account + " in region " + aws_region + ".")
            sts = boto3.client('sts')
            RoleArn = 'arn:aws:iam::%s:role/Assisted_Log_Enabler_IAM_Role' % org_account
            logging.info('Assuming Target Role %s for Assisted Log Enabler...' % RoleArn)
            assisted_log_enabler_sts = sts.assume_role(
                RoleArn=RoleArn,
                RoleSessionName='assisted-log-enabler-activation',
                DurationSeconds=3600,
            )
            elbv1_ma = boto3.client(
            'elb',
            aws_access_key_id=assisted_log_enabler_sts['Credentials']['AccessKeyId'],
            aws_secret_access_key=assisted_log_enabler_sts['Credentials']['SecretAccessKey'],
            aws_session_token=assisted_log_enabler_sts['Credentials']['SessionToken'],
            region_name=aws_region
            )
            elbv2_ma = boto3.client(
            'elbv2',
            aws_access_key_id=assisted_log_enabler_sts['Credentials']['AccessKeyId'],
            aws_secret_access_key=assisted_log_enabler_sts['Credentials']['SecretAccessKey'],
            aws_session_token=assisted_log_enabler_sts['Credentials']['SessionToken'],
            region_name=aws_region
            )
            s3_ma = boto3.client(
            's3',
            aws_access_key_id=assisted_log_enabler_sts['Credentials']['AccessKeyId'],
            aws_secret_access_key=assisted_log_enabler_sts['Credentials']['SecretAccessKey'],
            aws_session_token=assisted_log_enabler_sts['Credentials']['SessionToken'],
            region_name=aws_region
            )
            try:
                ELBList1: list = []
                ELBList2: list = []
                ELBLogList: list = []
                ELBv1LogList: list = []
                ELBv2LogList: list = []
                logging.info("DescribeLoadBalancers API Call")
                ELBList1 = elbv1_ma.describe_load_balancers()
                for lb in ELBList1['LoadBalancerDescriptions']:
                    logging.info("DescribeLoadBalancerAttibute API Call")
                    lblog=elbv1_ma.describe_load_balancer_attributes(LoadBalancerName=lb['LoadBalancerName'])
                    logging.info("Parsing out for ELB Access Logging")
                    if lblog['LoadBalancerAttributes']['AccessLog']['Enabled'] == False:
                        ELBv1LogList.append([lb['LoadBalancerName'],'classic'])
                logging.info("DescribeLoadBalancers v2 API Call")
                ELBList2 = elbv2_ma.describe_load_balancers()
                for lb in ELBList2['LoadBalancers']:
                    logging.info("DescribeLoadBalancerAttibute v2 API Call")
                    lblog=elbv2_ma.describe_load_balancer_attributes(LoadBalancerArn=lb['LoadBalancerArn'])
                    logging.info("Parsing out for ELBv2 Access Logging")
                    for lbtemp in lblog['Attributes']:
                        if lbtemp['Key'] == 'access_logs.s3.enabled':
                            if lbtemp['Value'] == 'false':
                                ELBv2LogList.append([lb['LoadBalancerName'],lb['LoadBalancerArn']])
                ELBLogList=ELBv1LogList+ELBv2LogList      
                if ELBLogList != []:
                    logging.info("List of Load Balancers found within account " + org_account + ", region " + aws_region + " without logging enabled:")
                    print(ELBLogList)
                    for elb in ELBLogList:
                        logging.info(elb[0] + " does not have Load Balancer logging on. It will be turned on within this function.")
                    logging.info("Creating S3 Logging Bucket for Load Balancers")
                    """Function to create the bucket for storing load balancer logs"""
                    logging.info("Creating bucket in %s" % org_account)
                    logging.info("CreateBucket API Call")
                    if aws_region == 'us-east-1':
                        logging_bucket_dict = s3_ma.create_bucket(
                            Bucket="aws-lb-log-collection-" + org_account + "-" + aws_region + "-" + unique_end
                        )
                    else:
                        logging_bucket_dict = s3_ma.create_bucket(
                            Bucket="aws-lb-log-collection-" + org_account + "-" + aws_region + "-" + unique_end,
                            CreateBucketConfiguration={
                                'LocationConstraint': aws_region
                            }
                        )
                    logging.info("Bucket " + "aws-lb-log-collection-" + org_account + "-" + aws_region + "-" + unique_end + " Created.")
                    logging.info("Setting lifecycle policy.")
                    logging.info("PutBucketLifecycleConfiguration API Call")
                    lifecycle_policy = s3_ma.put_bucket_lifecycle_configuration(
                        Bucket="aws-lb-log-collection-" + org_account + "-" + aws_region + "-" + unique_end,
                        LifecycleConfiguration={
                            'Rules': [
                                {
                                    'Expiration': {
                                        'Days': 365
                                    },
                                    'Status': 'Enabled',
                                    'Prefix': '',
                                    'ID': 'LogStorage',
                                    'Transitions': [
                                        {
                                            'Days': 90,
                                            'StorageClass': 'INTELLIGENT_TIERING'
                                        }
                                    ]
                                }
                            ]
                        }
                    )
                    logging.info("Lifecycle Policy successfully set.")
                    logging.info("Checking for AWS Log Account for ELB.")
                    logging.info("https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-access-logs.html")
                    if aws_region == 'us-east-1':
                        elb_account='127311923021'
                    elif aws_region == 'us-east-2':
                        elb_account='033677994240'
                    elif aws_region == 'us-west-1':
                        elb_account='027434742980'
                    elif aws_region == 'us-west-2':
                        elb_account='797873946194'
                    elif aws_region == 'af-south-1':
                        elb_account='098369216593'
                    elif aws_region == 'ca-central-1':
                        elb_account='985666609251'
                    elif aws_region == 'eu-central-1':
                        elb_account='054676820928'
                    elif aws_region == 'eu-west-1':
                        elb_account='156460612806'
                    elif aws_region == 'eu-west-2':
                        elb_account='652711504416'
                    elif aws_region == 'eu-south-1':
                        elb_account='635631232127'
                    elif aws_region == 'eu-west-3':
                        elb_account='009996457667'
                    elif aws_region == 'eu-north-1':
                        elb_account='897822967062'
                    elif aws_region == 'ap-east-1':
                        elb_account='754344448648'
                    elif aws_region == 'ap-northeast-1':
                        elb_account='582318560864'
                    elif aws_region == 'ap-northeast-2':
                        elb_account='600734575887'
                    elif aws_region == 'ap-northeast-3':
                        elb_account='383597477331'
                    elif aws_region == 'ap-southeast-1':
                        elb_account='114774131450'
                    elif aws_region == 'ap-southeast-2':
                        elb_account='783225319266'
                    elif aws_region == 'ap-south-1':
                        elb_account='718504428378'
                    elif aws_region == 'me-south-1':
                        elb_account='076674570225'
                    elif aws_region == 'sa-east-1':
                        elb_account='507241528517'
                    logging.info("Checking for AWS Log Account for ELB.")
                    logging.info("PutBucketPolicy API Call")
                    bucket_policy = s3_ma.put_bucket_policy(
                        Bucket="aws-lb-log-collection-" + org_account + "-" + aws_region + "-" + unique_end,
                        Policy='{"Version": "2012-10-17", "Statement": [{"Effect": "Allow","Principal": {"Service": "delivery.logs.amazonaws.com"},"Action": "s3:GetBucketAcl","Resource": "arn:aws:s3:::aws-lb-log-collection-' + org_account + '-' + aws_region + '-' + unique_end + '"},{"Effect": "Allow","Principal": {"Service": "delivery.logs.amazonaws.com"},"Action": "s3:PutObject","Resource": "arn:aws:s3:::aws-lb-log-collection-' + org_account + '-' + aws_region + '-' + unique_end + '/*","Condition": {"StringEquals": {"s3:x-amz-acl": "bucket-owner-full-control"}}},{"Effect": "Allow","Principal": {"AWS": "arn:aws:iam::' + elb_account + ':root"},"Action": "s3:PutObject","Resource": "arn:aws:s3:::aws-lb-log-collection-' + org_account + '-' + aws_region + '-' + unique_end + '/*"}]}'
                    )
                    logging.info("Setting the S3 bucket Public Access to Blocked")
                    logging.info("PutPublicAccessBlock API Call")
                    bucket_private = s3_ma.put_public_access_block(
                        Bucket="aws-lb-log-collection-" + org_account + "-" + aws_region + "-" + unique_end,
                        PublicAccessBlockConfiguration={
                            'BlockPublicAcls': True,
                            'IgnorePublicAcls': True,
                            'BlockPublicPolicy': True,
                            'RestrictPublicBuckets': True
                        },
                    )
                    if ELBv1LogList != []:
                        for elb in ELBv1LogList:
                            logging.info("Activating logs for Load Balancer " + elb[0])
                            logging.info("ModifyLoadBalancerAttributes API Call")
                            create_lb_log = elbv1_ma.modify_load_balancer_attributes(
                                LoadBalancerName=elb[0],
                                LoadBalancerAttributes={
                                    'AccessLog': {
                                        'Enabled': True,
                                        'S3BucketName': "aws-lb-log-collection-" + org_account + "-" + aws_region + "-" + unique_end,
                                        'EmitInterval': 5,
                                        'S3BucketPrefix': elb[0]
                                    }
                                }
                            )
                            logging.info("Logging Enabled for Load Balancer " + elb[0])
                    if ELBv2LogList != []:
                        for elb in ELBv2LogList:
                            logging.info("Activating logs for Load Balancer " + elb[0])
                            logging.info("ModifyLoadBalancerAttributes v2 API Call")
                            create_lb_log = elbv2_ma.modify_load_balancer_attributes(
                                LoadBalancerArn=elb[1],
                                Attributes=[
                                    {
                                        'Key': 'access_logs.s3.enabled',
                                        'Value': 'true'
                                    },
                                    {
                                        'Key': 'access_logs.s3.bucket',
                                        'Value': "aws-lb-log-collection-" + org_account + "-" + aws_region + "-" + unique_end
                                    },
                                    {
                                        'Key': 'access_logs.s3.prefix',
                                        'Value': elb[0]
                                    }
                                ]
                            )
                            logging.info("Logging Enabled for Load Balancer " + elb[0])
                else: 
                    logging.info("No Load Balancers WITHOUT logging found within account " + org_account + ", region " + aws_region + ":")
            except Exception as exception_handle:
                logging.error(exception_handle)


def run_eks():
    """Function that runs the defined EKS logging code"""
    OrgAccountIdList, organization_id = org_account_grab()
    eks_logging(region_list, OrgAccountIdList)
    logging.info("This is the end of the script. Please feel free to validate that logs have been turned on.")


def run_vpc_flow_logs():
    """Function that runs the defined VPC Flow Log logging code"""
    unique_end = random_string_generator()
    account_number = get_account_number()
    OrgAccountIdList, organization_id = org_account_grab()
    create_bucket(organization_id, account_number, unique_end)
    flow_log_activator(account_number, OrgAccountIdList, region_list, unique_end)
    logging.info("This is the end of the script. Please feel free to validate that logs have been turned on.")
    

def run_r53_query_logs():
    """Function that runs the defined R53 Query Logging code"""
    unique_end = random_string_generator()
    account_number = get_account_number()
    OrgAccountIdList, organization_id = org_account_grab()
    create_bucket(organization_id, account_number, unique_end)
    route_53_query_logs(region_list, account_number, OrgAccountIdList, unique_end)
    logging.info("This is the end of the script. Please feel free to validate that logs have been turned on.")

def run_s3_logs():
    """Function that runs the defined Bucket Logging code"""
    unique_end = random_string_generator()
    account_number = get_account_number()
    OrgAccountIdList, organization_id = org_account_grab()
    s3_logs(region_list, account_number, OrgAccountIdList, unique_end)
    logging.info("This is the end of the script. Please feel free to validate that logs have been turned on.")

def run_lb_logs():
    """Function that runs the defined Load Balancer Logging code"""
    unique_end = random_string_generator()
    account_number = get_account_number()
    OrgAccountIdList, organization_id = org_account_grab()
    lb_logs(region_list, account_number, OrgAccountIdList, unique_end)
    logging.info("This is the end of the script. Please feel free to validate that logs have been turned on.")

def lambda_handler(event, context):
    """Function that runs all of the previously defined functions"""
    unique_end = random_string_generator()
    account_number = get_account_number()
    OrgAccountIdList, organization_id = org_account_grab()
    create_bucket(organization_id, account_number, unique_end)
    flow_log_activator(account_number, OrgAccountIdList, region_list, unique_end)
    eks_logging(region_list, OrgAccountIdList)
    route_53_query_logs(region_list, account_number, OrgAccountIdList, unique_end)
    s3_logs(region_list, account_number, OrgAccountIdList, unique_end)
    lb_logs(region_list, account_number, OrgAccountIdList, unique_end)
    logging.info("This is the end of the script. Please feel free to validate that logs have been turned on.")


if __name__ == '__main__':
    event = "event"
    context = "context"
    lambda_handler(event, context)

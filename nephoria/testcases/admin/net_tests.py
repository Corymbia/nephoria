#!/usr/bin/python
# Software License Agreement (BSD License)
#
# Copyright (c) 2009-2011, Eucalyptus Systems, Inc.
# All rights reserved.
#
# Redistribution and use of this software in source and binary forms, with or
# without modification, are permitted provided that the following conditions
# are met:
#
#   Redistributions of source code must retain the above
#   copyright notice, this list of conditions and the
#   following disclaimer.
#
#   Redistributions in binary form must reproduce the above
#   copyright notice, this list of conditions and the
#   following disclaimer in the documentation and/or other
#   materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# Author:

__author__ =  'matt.clark@eucalyptus.com'
'''
Test case class to test points of network security groups
See individual test descriptions for test objectives.
test1:
    Definition:
        Create test instances within each zone within security group1. This security group is authorized for
        ssh access from 0.0.0.0/0.
        This test attempts the following:
            -To run an instance in each zone and confirm it reaches 'running' state.
            -Confirm the instance is ping-able from the cc within a given timeout
            -Establish and verify an ssh session directly from the local machine running this test.
            -Place ssh key on instance for later use
            -Add instance to global 'group1_instances'

test2:
    Definition:
        This test attempts to create an instance in each within security group2 which should not
        be authorized for any remote access (outside of the CC).
        The test attempts the following:
            -To run an instance in each zone and confirm it reaches 'running' state.
            -Confirm the instance is ping-able from the cc within a given timeout
            -Establish and verify an ssh session using the cc as a proxy.
            -Place ssh key on instance for later use
            -Add instance to global 'group2_instances'

test3:
    Definition:
        This test attempts to set up security group rules between group1 and group2 to authorize group2 access
        from group1. If use_cidr is True security groups will be setup using cidr notication ip/mask for each instance in
        group1, otherwise the entire source group 1 will authorized.
        the group will be
        Test attempts to:
            -Authorize security groups for inter group private ip access.
            -Iterate through each zone and attempt to ssh from an instance in group1 to an instance in group2 over their
                private ips.

test4:
    Definition:
        Test attempts to verify that the local machine cannot ssh to the instances within group2 which is not authorized
        for ssh access from this source.

test5 (Multi-zone/cluster env):
    Definition:
        This test attempts to check connectivity for instances in the same security group, but in different zones.
        Note: This test requires the CC have tunnelling enabled, or the CCs in each zone be on same
        layer 2 network segment.
        Test attempts to:
            -Iterate through each zone and attempt to ssh from an instance in group1 to an instance in a separate zone
             but same security group1 over their private ips.

test 6 (Multi-zone/cluster env):
    Definition:
        This test attempts to set up security group rules between group1 and group2 to authorize group2 access
        from group1 across different zones.
        If no_cidr is True security groups will be setup using cidr notication ip/mask for each instance in
        group1, otherwise the entire source group 1 will authorized.
        the group will be
        Note: This test requires the CC have tunnelling enabled, or the CCs in each zone be on same
        layer 2 network segment.
        Test attempts to:
            -Authorize security groups for inter group private ip access.
            -Iterate through each zone and attempt to ssh from an instance in group1 to an instance in group2 over their
             private ips.


'''

#todo: Make use of CC optional so test can be run with only creds and non-admin user.
# CC only provides additional point of debug so can be removed from test for non-euca testing
#todo: Allow test to run with an admin and non-admin account, so debug can be provided through admin and test can
# be run under non-admin if desired.

from paramiko import SSHException
from nephoria.euca.euca_ops import Eucaops
from nephoria.utils.eutestcase import EutesterTestCase, SkipTestException
from nephoria.aws.ec2.euinstance import EuInstance
from nephoria.utils.sshconnection import CommandExitCodeException, SshConnection
import socket
import time
import os
import sys


class TestZone():
    def __init__(self, zonename):
        self.name = zonename
        self.zone = zonename
        self.test_instance_group1 = None
        self.test_instance_group2 = None


class Net_Tests(EutesterTestCase):

    def __init__(self,  tester=None, **kwargs):
        self.setuptestcase()
        self.setup_parser()
        self.parser.add_argument("--freeze_on_fail",
                                 action='store_true',
                                 help="Boolean flag to avoid cleaning test resources upon failure, default: True ",
                                 default=False)
        self.tester = tester
        self.get_args()
        # Allow __init__ to get args from __init__'s kwargs or through command line parser...
        for kw in kwargs:
            print 'Setting kwarg:'+str(kw)+" to "+str(kwargs[kw])
            self.set_arg(kw ,kwargs[kw])
        self.show_args()
        ### Create the Eucaops object, by default this will be Eucalyptus/Admin and have ssh access to components
        if not tester and not self.args.config:
            print "Need nephoria config file to execute this test. As well as system ssh credentials (key, password, etc)"
            self.parser.print_help()
            sys.exit(1)
        # Setup basic nephoria object
        if not self.tester:
            self.debug('Creating Eucaops tester object from args provided...')
            self.tester = self.do_with_args(Eucaops)
            self.tester.debug = lambda msg: self.debug(msg, traceback=2, linebyline=False)
        assert isinstance(self.tester, Eucaops)
        self.cc_last_checked = time.time()

        ### Create local zone list to run tests in
        if self.args.zone:
            self.zones = str(self.args.zone).replace(',',' ')
            self.zones = self.zones.split()
        else:
            self.zones = self.tester.ec2.get_zones()
        if not self.zones:
            raise Exception('No zones found to run this test?')
        self.debug('Running test against zones:' + ",".join(self.zones))

        ### Add and authorize securtiy groups
        self.debug("Creating group1..")
        self.group1 = self.tester.ec2.add_group(str(self.name) + "_group1_" + str(time.time()))
        self.debug("Authorize ssh for group1 from '0.0.0.0/0'")
        self.tester.ec2.authorize_group(self.group1, port=22, protocol='tcp', cidr_ip='0.0.0.0/0')
        #self.tester.authorize_group(self.group1, protocol='icmp',port='-1')

        self.debug("Creating group2, will authorize later from rules within test methods..")
        self.group2 = self.tester.ec2.add_group(str(self.name) + "_group2_" + str(time.time()))
        self.group1_instances = []
        self.group2_instances = []



        ### Generate a keypair for the instances
        try:
            keys = self.tester.ec2.get_all_current_local_keys()
            if keys:
                self.keypair = keys[0]
            else:
                self.keypair = self.tester.ec2.create_keypair_and_localcert(str(self.name) + "_key_" + str(time.time()))
        except Exception, ke:
            raise Exception("Failed to find/create a keypair, error:" + str(ke))

        ### Get an image to work with
        if self.args.emi:
            self.image = self.tester.ec2.get_emi(emi=str(self.args.emi))
        else:
            self.image = self.tester.ec2.get_emi(root_device_type="instance-store", basic_image=True)
        if not self.image:
            raise Exception('couldnt find instance store image')

    ######################################################
    #   Test Utility Methods
    ######################################################
    def authorize_group_for_instance_list(self, group, instances):
        for instance in instances:
            assert isinstance(instance, EuInstance)
            self.tester.ec2.authorize_group(group, cidr_ip=instance.private_ip_address + "/32")

    def revoke_group_for_instance_list(self, group, instances):
        for instance in instances:
            assert isinstance(instance, EuInstance)
            self.tester.ec2.revoke(group, cidr_ip=instance.private_ip_address + "/32")

    def clean_method(self):
        if self.args.freeze_on_fail:
            self.status('freeze_on_fail arg set, not cleaning test resources')
        else:
            self.tester.cleanup_artifacts()

    def get_proxy_machine(self, instance):
        prop = self.tester.property_manager.get_property('networkmode',
                                                         'cluster',
                                                         instance.placement)
        if prop.value.lower() == "edge":
            proxy_machine = self.get_active_nc_for_instance(instance)
        else:
            proxy_machine = self.get_active_cc_for_instance(instance)
        self.debug("Instance is running on: " + proxy_machine.hostname)
        return proxy_machine

    def create_ssh_connection_to_instance(self, instance, retry=10):
        proxy_machine = self.get_proxy_machine(instance)
        ssh = None
        attempts = 0
        elapsed = 0
        next_retry_time = 10
        start = time.time()
        proxy_keypath=proxy_machine.machine.ssh.keypath or None
        while not ssh and attempts < retry:
            attempts += 1
            elapsed = int(time.time()-start)
            self.debug('Attempting to ssh to instances private ip:' + str(instance.private_ip_address) +
                       'through the cc ip:' + str(proxy_machine.hostname) + ', attempts:' +str(attempts) + "/" + str(retry) +
                       ", elapsed:" + str(elapsed))
            try:
                ssh = SshConnection(host=instance.private_ip_address,
                                keypath=instance.keypath,
                                proxy=proxy_machine.hostname,
                                proxy_username=proxy_machine.machine.ssh.username,
                                proxy_password=proxy_machine.machine.ssh.password,
                                proxy_keypath=proxy_keypath)
            except Exception, ce:
                tb = self.tester.get_traceback()
                if attempts >= retry:
                    self.debug("\n" + tb,linebyline=False)
                self.debug('Failed to connect error:' + str(ce))
            if attempts < retry:
                    time.sleep(next_retry_time)

        if not ssh:
            raise Exception('Could not ssh to instances private ip:' + str(instance.private_ip_address) +
                            ' through the cc ip:' + str(proxy_machine.hostname) + ', attempts:' +str(attempts) + "/" + str(retry) +
                            ", elapsed:" + str(elapsed))

        return ssh

    def get_active_cc_for_instance(self,instance,refresh_active_cc=30):
        elapsed = time.time()-self.cc_last_checked
        self.cc_last_checked = time.time()
        if elapsed > refresh_active_cc:
            use_cached_list = False
        else:
            use_cached_list = True
        cc = self.tester.service_manager.get_all_cluster_controllers(partition=instance.placement,
                                                                     use_cached_list= use_cached_list,
                                                                     state='ENABLED')[0]
        return cc

    def get_active_nc_for_instance(self,instance):
        nc = self.tester.service_manager.get_all_node_controllers(instance_id=instance.id, use_cached_list=False).pop()
        return nc

    def ping_instance_private_ip_from_active_cc(self, instance):
        assert isinstance(instance, EuInstance)
        proxy_machine = self.get_proxy_machine(instance)
        try:
            proxy_machine.machine.ping_check(instance.private_ip_address)
            return True
        except:pass
        return False


    def is_port_in_use_on_instance(self, instance, port, tcp=True, ipv4=True):
        args = '-ln'
        if tcp:
            args += 't'
        else:
            args += 'u'
        if ipv4:
            args += '4'
        else:
            args += '6'
        use = instance.sys("netstat " + str(args) + " | awk '$6 ==" +
                           ' "LISTEN" && $4 ~ ".' + str(port) +
                           '"' + "' | grep LISTEN")
        if use:
            self.debug('Port {0} IS in use on instance:'
                       .format(port, instance.id))
            return True
        else:
            self.debug('Port {0} IS NOT in use on instance:'
                       .format(port, instance.id))
            False

    def is_port_range_in_use_on_instance(self, instance, start, end,
                                         tcp=True, ipv4=True):
        for x in xrange(start, end):
            if self.is_port_in_use_on_instance(instance=instance,
                                               port=x,
                                               tcp=tcp,
                                               ipv4=ipv4):
                return True
        return False

    ################################################################
    #   Test Methods
    ################################################################
    def test1_create_instance_in_zones_for_security_group1(self, ping_timeout=180, zones=None):
        """
        Definition:
        Create test instances within each zone within security group1. This security group is authorized for
        ssh access from 0.0.0.0/0.
        This test attempts the following:
            -To run an instance in each zone and confirm it reaches 'running' state.
            -Confirm the instance is ping-able from the cc within a given timeout
            -Establish and verify an ssh session directly from the local machine running this test.
            -Place ssh key on instance for later use
            -Add instance to global 'group1_instances'
        """
        if zones and not isinstance(zones, list):
            zones = [zones]
        zones = zones or self.zones
        for zone in zones:
            #Create an instance, monitor it's state but disable the auto network/connect checks till afterward
            instance = self.tester.ec2.run_image(image=self.image,
                                                 keypair=self.keypair,
                                                 group=self.group1,
                                                 zone=zone,
                                                 auto_connect=False,
                                                 monitor_to_running=False)[0]
            self.group1_instances.append(instance)
        self.tester.ec2.monitor_euinstances_to_running(self.group1_instances)
        #Now run the network portion.
        for instance in self.group1_instances:
            self.status('Checking connectivity to:' + str(instance.id) + ":" + str(instance.private_ip_address)+
                        ", zone:" + str(instance.placement) )
            assert isinstance(instance, EuInstance)
            self.debug('Attempting to ping instances private ip from cc...')
            self.tester.wait_for_result(self.ping_instance_private_ip_from_active_cc,
                                        result=True,
                                        timeout=ping_timeout,
                                        instance=instance)
            self.debug('Attempting to ssh to instance from local test machine...')
            self.debug('Check some debug information re this data connection in this security group first...')
            self.tester.ec2.does_instance_sec_group_allow(instance=instance,
                                                          src_addr=None,
                                                          protocol='tcp',
                                                          port=22)
            instance.connect_to_instance(timeout=90)
            self.status('SSH connection to instance:' + str(instance.id) +
                        ' successful to public ip:' + str(instance.ip_address) +
                        ', zone:' + str(instance.placement))
            instance.sys('uname -a', code=0)
            instance.ssh.sftp_put(instance.keypath, os.path.basename(instance.keypath))
            instance.sys('chmod 0600 ' + os.path.basename(instance.keypath), code=0 )

    def test2_create_instance_in_zones_for_security_group2(self, ping_timeout=180, auto_connect=False, zones=None):
        """
        Definition:
        This test attempts to create an instance in each zone within security group2 which should not
        be authorized for any remote access (outside of the CC).
        The test attempts the following:
            -To run an instance in each zone and confirm it reaches 'running' state.
            -Confirm the instance is ping-able from the cc within a given timeout
            -Establish and verify an ssh session using the cc as a proxy.
            -Place ssh key on instance for later use
            -Add instance to global 'group2_instances'
        :params ping_timeout: Int Time to wait for ping for successful ping to instance(s)
        :params auto_connect: Boolean. If True will auto ssh to instance(s), if False will
                              use cc/nc as ssh proxy
        :params zones: List of names of Availability zone(s) to create instances in
        """
        if zones and not isinstance(zones, list):
            zones = [zones]
        zones = zones or self.zones
        for zone in self.zones:
            instance = self.tester.ec2.run_image(image=self.image,
                                             keypair=self.keypair,
                                             group=self.group2,
                                             zone=zone,
                                             auto_connect=auto_connect,
                                             monitor_to_running=False)[0]
            self.group2_instances.append(instance)
        self.tester.ec2.monitor_euinstances_to_running(self.group2_instances)
        for instance in self.group2_instances:
            self.status('Checking connectivity to:' + str(instance.id) + ":" + str(instance.private_ip_address)+
                        ", zone:" + str(instance.placement))
            assert isinstance(instance, EuInstance)
            self.tester.wait_for_result(self.ping_instance_private_ip_from_active_cc,
                                        result=True,
                                        timeout=ping_timeout,
                                        instance=instance)
            if not auto_connect:
                self.status('Make sure ssh is working through CC path before trying between instances...')
                instance.proxy_ssh = self.create_ssh_connection_to_instance(instance)
                self.status('SSH connection to instance:' + str(instance.id) +
                            ' successful to private ip:' + str(instance.private_ip_address) +
                            ', zone:' + str(instance.placement))
            else:
                instance.proxy_ssh = instance.ssh
            instance.proxy_ssh.sys('uname -a', code=0)
            self.status('Uploading keypair to instance in group2...')
            instance.proxy_ssh.sftp_put(instance.keypath, os.path.basename(instance.keypath))
            instance.proxy_ssh.sys('chmod 0600 ' + os.path.basename(instance.keypath), code=0 )
            self.status('Done with create instance security group2:' + str(instance.id))

    def test3_test_ssh_between_instances_in_diff_sec_groups_same_zone(self):
        '''
        Definition:
        This test attempts to set up security group rules between group1 and group2 to authorize group2 access
        from group1. If no_cidr is True security groups will be setup using cidr notation ip/mask for each instance in
        group1, otherwise the entire source group 1 will be authorized.

        Test attempts to:
            -Authorize security groups for inter group private ip access.
            -Iterate through each zone and attempt to ssh from an instance in group1 to an instance in group2 over their
                private ips.
            - Run same 2 tests from above by authorizing a SecurityGroup
        '''
        def check_instance_connectivity():
            for zone in self.zones:
                instance1 = None
                instance2 = None
                for instance in self.group1_instances:
                    if instance.placement == zone:
                        assert isinstance(instance, EuInstance)
                        instance1 = instance
                        break
                if not instance1:
                    raise Exception('Could not find instance in group1 for zone:' + str(zone))

                for instance in self.group2_instances:
                    if instance.placement == zone:
                        assert isinstance(instance, EuInstance)
                        instance2 = instance
                        break
                if not instance2:
                    raise Exception('Could not find instance in group2 for zone:' + str(zone))
            self.debug('Attempting to run ssh command "uname -a" between instances across security groups:\n'
                       + str(instance1.id) + '/sec grps(' + str(instance1.security_groups)+") --> "
                       + str(instance2.id) + '/sec grps(' + str(instance2.security_groups)+")\n"
                       + "Current test run in zone: " + str(zone), linebyline=False )
            self.debug('Check some debug information re this data connection in this security group first...')
            self.tester.ec2.does_instance_sec_group_allow(instance=instance2,
                                                      src_addr=instance1.private_ip_address,
                                                      protocol='tcp',
                                                      port=22)
            self.debug('Now Running the ssh command...')
            instance1.sys("ssh -o StrictHostKeyChecking=no -i "
                          + str(os.path.basename(instance1.keypath))
                          + " root@" + str(instance2.private_ip_address)
                          + " 'uname -a'", code=0)
            self.debug('Ssh between instances passed')

        self.authorize_group_for_instance_list(self.group2, self.group1_instances)
        check_instance_connectivity()
        self.revoke_group_for_instance_list(self.group2, self.group1_instances)
        self.tester.ec2.authorize_group(self.group2, cidr_ip=None, port=None, src_security_group_name=self.group1.name )
        check_instance_connectivity()

    def test4_attempt_unauthorized_ssh_from_test_machine_to_group2(self):
        '''
        Description:
        Test attempts to verify that the local machine cannot ssh to the instances within group2 which is not authorized
        for ssh access from this source.
        '''
        for instance in self.group2_instances:
            assert isinstance(instance, EuInstance)
            #Provide some debug information re this data connection in this security group
            self.tester.ec2.does_instance_sec_group_allow(instance=instance, src_addr=None, protocol='tcp',port=22)
            try:
                instance.reset_ssh_connection(timeout=5)
                raise Exception('Was able to connect to instance: ' + str(instance.id) + ' in security group:'
                                + str(self.group2.name))
            except:
                self.debug('Success: Was not able to ssh from the local machine to instance in unauthorized sec group')

    def test5_test_ssh_between_instances_in_same_sec_groups_different_zone(self):
        '''
        Definition:
        This test attempts to check connectivity for instances in the same security group, but in different zones.
        Note: This test requires the CC have tunnelling enabled, or the CCs in each zone be on same
        layer 2 network segment.

        Test attempts to:
            -Iterate through each zone and attempt to ssh from an instance in group1 to an instance in a separate zone
             but same security group1 over their private ips.
        '''
        zones = []
        if len(self.zones) < 2:
            raise SkipTestException('Skipping test5, only a single zone found or provided')

        for zone in self.zones:
            zones.append(TestZone(zone))
            #Grab a single instance from each zone within security group1
        for zone in zones:
            instance = None
            for instance in self.group1_instances:
                if instance.placement == zone.zone:
                    assert isinstance(instance, EuInstance)
                    zone.test_instance_group1 = instance
                    break
                instance = None
            if not zone.test_instance_group1:
                raise Exception('Could not find an instance in group1 for zone:' + str(zone.zone))

        self.debug('Iterating through zones, attempting ssh between zones within same security group...')
        for zone in zones:
            instance1 = zone.test_instance_group1
            for zone2 in zones:
                if zone.zone != zone2.zone:
                    instance2 = zone2.test_instance_group1
                    if not instance1 or not instance2:
                        raise Exception('Security group: ' + str(self.group1.name) + ", missing instances in a Zone:"
                                        + str(zone.zone) + " = instance:" + str(instance1) +
                                        ", Zone:" + str(zone2.zone) + " = instance:" + str(instance2))
                    self.debug('Attempting to run ssh command "uname -a" between instances across zones and security groups:\n'
                               + str(instance1.id) + '/sec grps(' + str(instance1.security_groups)+") --> "
                               + str(instance2.id) + '/sec grps(' + str(instance2.security_groups)+")\n"
                               + "Current test run in zones: " + str(instance1.placement) + "-->" + str(instance2.placement),
                               linebyline=False )
                    self.debug('Check some debug information re this data connection in this security group first...')
                    self.tester.ec2.does_instance_sec_group_allow(instance=instance2,
                                                              src_addr=instance1.private_ip_address,
                                                              protocol='tcp',
                                                              port=22)
                    self.debug('Now Running the ssh command...')
                    instance1.sys("ssh -o StrictHostKeyChecking=no -i "
                                  + str(os.path.basename(instance1.keypath))
                                  + " root@" + str(instance2.private_ip_address)
                                  + " ' uname -a'", code=0)
                    self.debug('Ssh between instances passed')




    def test6_test_ssh_between_instances_in_diff_sec_groups_different_zone(self):
        '''
        Definition:
        This test attempts to set up security group rules between group1 and group2 to authorize group2 access
        from group1 across different zones.
        If no_cidr is True security groups will be setup using cidr notication ip/mask for each instance in
        group1, otherwise the entire source group 1 will authorized.
        the group will be
        Note: This test requires the CC have tunnelling enabled, or the CCs in each zone be on same
        layer 2 network segment.

        Test attempts to:
            -Authorize security groups for inter group private ip access.
            -Iterate through each zone and attempt to ssh from an instance in group1 to an instance in group2 over their
                private ips.
        '''
        zones = []
        if len(self.zones) < 2:
            raise SkipTestException('Skipping test5, only a single zone found or provided')
        self.status('Authorizing group2:' + str(self.group2.name) + ' for access from group1:' + str(self.group1.name))
        self.tester.ec2.authorize_group(self.group2, cidr_ip=None, port=None, src_security_group_name=self.group1.name)


        for zone in self.zones:
            zones.append(TestZone(zone))


        self.debug('Grabbing  a single instance from each zone and from each test security group to use in this test...')
        for zone in zones:
            instance = None
            for instance in self.group1_instances:
                if instance.placement == zone.zone:
                    assert isinstance(instance, EuInstance)
                    zone.test_instance_group1 = instance
                    break
                instance = None
            if not zone.test_instance_group1:
                raise Exception('Could not find an instance in group1 for zone:' + str(zone.zone))
            instance = None
            for instance in self.group2_instances:
                if instance.placement == zone.zone:
                    assert isinstance(instance, EuInstance)
                    zone.test_instance_group2 = instance
                    break
            if not zone.test_instance_group2:
                raise Exception('Could not find instance in group2 for zone:' + str(zone.zone))
            instance = None

        self.status('Checking connectivity for instances in each zone, in separate but authorized security groups...')
        for zone in zones:
            instance1 = zone.test_instance_group1
            if not instance1:
                raise Exception('Missing instance in Security group: ' + str(self.group1.name) + ', Zone:' +
                                str(zone) + " = instance:" + str(instance1) )
            for zone2 in zones:
                if zone.zone != zone2.zone:
                    instance2 = zone2.test_instance_group2
                    if not instance2:
                        raise Exception('Missing instance in Security group: ' + str(self.group2.name) + ', Zone:' +
                                        str(zone2.zone) + " = instance:" + str(instance2) )
                    self.debug('Attempting to run ssh command "uname -a" between instances across zones and security groups:\n'
                               + str(instance1.id) + '/sec grps(' + str(instance1.security_groups)+") --> "
                               + str(instance2.id) + '/sec grps(' + str(instance2.security_groups)+")\n"
                               + "Current test run in zones: " + str(instance1.placement) + "-->" + str(instance2.placement),
                               linebyline=False )
                    self.debug('Check some debug information re this data connection in this security group first...')
                    self.tester.ec2.does_instance_sec_group_allow(instance=instance2,
                                                              src_addr=instance1.private_ip_address,
                                                              protocol='tcp',
                                                              port=22)
                    self.debug('Now Running the ssh command...')
                    instance1.sys("ssh -o StrictHostKeyChecking=no -i "
                                  + str(os.path.basename(instance1.keypath))
                                  + " root@" + str(instance2.private_ip_address)
                                  + " ' uname -a'", code=0)
                    self.debug('Ssh between instances passed')



    def test7_add_and_revoke_tcp_port_range(self,
                                            start=None,
                                            src_cidr_ip='0.0.0.0/0',
                                            count=10,
                                            instances=None):
        '''
        Definition:
        Attempts to add a range of ports to a security group and test
        the ports from the local machine to make sure they are available.
        Next the test revokes the ports and verifies they are no longer
        available.
        :param start: starting port of range to scan
        :param src_cidr_ip: cidr ip for src authorization. If None the test
                            will attempt to discovery the cidr ip of the
                            machine running this test to use for src auth ip.
        :param count: number of consecutive ports from 'start' to test
        :param tcp: boolean tcp if true, udp if false
        '''
        tester = self.tester
        assert isinstance(tester, Eucaops)

        if instances:
            if not isinstance(instances, list):
                instances = [instances]
            for instance in instances:
                assert isinstance(instance, EuInstance)
        else:
            instances = self.group1_instances
        if not instances:
            raise ValueError('Could not find instance in group1')

        # Iterate through all instances and test...
        for instance1 in instances:
            # Make sure we can ssh to this instance (note this may need to be
            # adjusted for windows access
            # 'does_instance_sec_group_allow' will set tester.ec2_source_ip to the
            # ip the local machine uses to communicate with the instance.
            if src_cidr_ip is None:
                if not tester.ec2.does_instance_sec_group_allow(instance=instance1,
                                                            protocol='tcp',
                                                            port=22):
                    src_cidr_ip = str(tester.ec2.ec2_source_ip) + '/32'
                    tester.ec2.authorize_group(self.group1,
                                           cidr_ip=src_cidr_ip,
                                           port=22)
            else:
                tester.ec2.authorize_group(self.group1,
                                            cidr_ip=src_cidr_ip,
                                            port=22)
            try:
                instance1.sys('which netcat', code=0)
            except CommandExitCodeException:
                try:
                    instance1.sys('apt-get install netcat -y', code=0)
                except CommandExitCodeException:
                    try:
                        instance1.sys('yum install netcat -y', code=0)
                    except:
                        self.debug('could install netcat on this instance')
                        raise

            #make sure we have an open port range to play with...
            if start is None:
                for x in xrange(2000, 65000):
                    if self.is_port_range_in_use_on_instance(instance=instance1,
                                                             start=x,
                                                             end=x+count,
                                                             tcp=True):
                        x = x + count
                    else:
                        start = x
                        break
                if not start:
                    raise RuntimeError('Free consecutive port range of count:{0} '
                                       'not found on instance:{1}'
                                       .format(count, instance1.id))
            # authorize entire port range...
            self.tester.ec2.authorize_group(self.group1,
                                        cidr_ip=src_cidr_ip,
                                        port=start,
                                        end_port=start+count)
            # test entire port range is accessible from this machine
            test_file = 'eutester_port_test.txt'
            #Allow some delay for the rule to be applied in the network...
            time.sleep(10)
            for x in xrange(start, start+count):
                # Set up socket listener with netcat, to make sure we're not
                # connecting to the CC or other device write port to file and
                # verify file contents as well.
                test_string = '{0} last port tested[{1}]'.format(time.time(), x)
                self.debug("Gathering debug information as to whether the "
                           "tester's src ip is authorized for this port test...")
                if not tester.ec2.does_instance_sec_group_allow(
                        instance=instance1,
                        src_addr=src_cidr_ip.split('/')[0],
                        protocol='tcp',
                        port=x):
                    raise ValueError('Group:{0} did not have {1}:{2} authorized'
                                     .format(self.group1.name,
                                             src_cidr_ip.split('/')[0],
                                             x))
                # start up netcat, sleep to allow nohup to work before quiting
                # the shell...
                instance1.sys('killall -9 netcat 2> /dev/null', timeout=5)
                instance1.sys('{' + ' ( nohup netcat -k -l {0} > {1} ) &  sleep 1; '
                              .format(x, test_file) + '}', code=0, timeout=5)
                # attempt to connect socket at instance/port and send the
                # test_string...
                time.sleep(2)  # Allow listener to setup...
                done = False
                attempt = 0
                while not done:
                    try:
                        attempt += 1
                        tester.test_port_status(ip=instance1.ip_address,
                                                port=x,
                                                tcp=True,
                                                send_buf=test_string,
                                                verbose=True)
                        done = True
                    except socket.error as SE:
                        self.debug('Failed to poll port status on attempt {0}'.format(attempt))
                        try:
                            self.debug('Failed to connect to "{0}":IP:"{1}":'
                                       'PORT:"{2}"'.format(instance1.id,
                                                           instance1.ip_address,
                                                           x))
                            tester.ec2.show_security_group(self.group1)
                            try:
                                self.debug('Getting netcat info from instance...')
                                instance1.sys('ps aux | grep netcat', timeout=10)
                            except CommandExitCodeException:
                                pass
                            self.debug('Iptables info from Euca network component '
                                       'responsible for this instance/security '
                                       'group...')
                            proxy_machine = self.get_proxy_machine(instance1)
                            proxy_machine.machine.sys('iptables-save', timeout=10)

                        except:
                            self.debug('Error when fetching debug output for '
                                       'failure, ignoring:' +
                                       str(tester.get_traceback()))
                        if attempt >= 2:
                            raise SE
                # Since no socket errors were encountered assume we connected,
                # check file on instance to make sure we didn't connect somewhere
                # else like the CC...
                instance1.sys('grep "{0}" {1}; echo "" > {1}'
                              .format(test_string, test_file),
                              code=0)
                self.status('Port "{0}" successfully tested on instance:{1}/{2}'
                           .format(x, instance1.id, instance1.ip_address))
            self.status('Authorizing port range {0}-{1} passed'
                        .format(start, start+count))

            self.status('Now testing revoking by removing the same port'
                        'range...')
            time.sleep(3)
            tester.ec2.revoke_security_group(group_name=self.group1.name,
                                             ip_protocol='tcp',
                                             from_port=start,
                                             to_port=start+count,
                                             cidr_ip=src_cidr_ip)
            #Allow some delay for the rule to be applied in the network...
            time.sleep(10)
            for x in xrange(start, start+count):
                # Set up socket listener with netcat, to make sure we're not
                # connecting to the CC or other device write port to file and
                # verify file contents as well.
                # This portion of the test expects that the connection will fail.
                test_string = '{0} last port tested[{1}]'.format(time.time(), x)
                self.debug("Gathering debug information as to whether the "
                           "tester's src ip is authorized for this port test...")
                if tester.ec2.does_instance_sec_group_allow(
                        instance=instance1,
                        src_addr=src_cidr_ip.split('/')[0],
                        protocol='tcp',
                        port=x):
                    raise ValueError('Group:{0} has {1}:{2} authorized after revoke'
                                     .format(self.group1.name,
                                             src_cidr_ip,
                                             x))
                try:
                    instance1.sys('killall -9 netcat 2> /dev/null', timeout=5)
                    instance1.sys('{' + ' ( nohup netcat -k -l {0} > {1} ) &  sleep 1; '
                              .format(x, test_file) + '}', code=0, timeout=5)
                    tester.test_port_status(ip=instance1.ip_address,
                                            port=x,
                                            tcp=True,
                                            send_buf=test_string,
                                            verbose=True)
                    #We may still need to test the file content for the UDP case...
                    # Since no socket errors were encountered assume we connected,
                    # check file on instance to make sure we didn't connect somewhere
                    # else like the CC. Dont' error here cuz it's already a bug...
                    instance1.sys('grep "{0}" {1}; echo "" > {1}'
                              .format(test_string, test_file))
                except (socket.error, CommandExitCodeException) as OK:
                    self.status('Port "{0}" successfully revoked on '
                                'instance:{1}/{2}'
                                .format(x, instance1.id, instance1.ip_address))
        self.status('Add and revoke ports test passed')

    def test8_verify_deleting_of_auth_source_group2(self):
        """
        Definition:
        Attempts to delete a security group which has been authorized by another security group.
        -Authorizes group1 access from group2
        -Validates connectivity for instances in group1 can be accessed from group2
        -Deletes group2, validates group1 still allows traffic from other authorized sources
        """
        zones = []
        for zone in self.zones:
            zones.append(TestZone(zone))
        tester = self.tester
        assert isinstance(tester, Eucaops)
        if not self.group1:
            raise ValueError('Group1 not found for this test')
        if not self.group1_instances:
            raise ValueError('No instances found from group1')
        #Clean out any existing rules in group1
        self.tester.ec2.revoke_all_rules(self.group1)
        instance1 = self.group1_instances[0]
        #Add back ssh
        assert not tester.ec2.does_instance_sec_group_allow(instance=instance1,
                                                         protocol='tcp',
                                                         port=22), \
            'Instance: {0}, security group still allows access after ' \
            'revoking all rules'

        tester.ec2.authorize_group(self.group1,
                               cidr_ip=str(tester.ec2.ec2_source_ip) + '/32',
                               port=22)
        for instance in self.group1_instances:
            instance.reset_ssh_connection()
            instance.sys('echo "reset ssh worked"', code=0)
        self.status('Authorizing group2 access to group1...')
        tester.ec2.authorize_group(self.group1,
                               cidr_ip=None,
                               port=None,
                               src_security_group_name=self.group2.name)
        tester.ec2.show_security_group(self.group1)
        for zone in zones:
            for instance in self.group1_instances:
                if instance.placement == zone.name:
                    zone.test_instance_group1 = instance
                    break
            for instance in self.group2_instances:
                if instance.placement == zone.name:
                    zone.test_instance_group2 = instance
                    break
            if not zone.test_instance_group1:
                raise ValueError('Could not find instances in sec group1'
                                 'group for zone:' + str(zone.name))
            if not zone.test_instance_group2:
                raise ValueError('Could not find instances in sec group2'
                                 'group for zone:' + str(zone.name))

        self.status('Checking auth from group2 to group1 instances...')
        self.debug('Check some debug information re this data '
                   'connection in this security group first...')
        assert isinstance(zone.test_instance_group1, EuInstance)
        assert isinstance(zone.test_instance_group2, EuInstance)
        for zone in zones:
            #Get the group2 instance from this zone
            allowed = False

            if self.tester.ec2.does_instance_sec_group_allow(
                    instance=zone.test_instance_group1,
                    src_group=self.group2,
                    protocol='icmp'):
                allowed = True
                break
            if not allowed:
                raise ValueError('Group2 instance not allowed in group1'
                                 ' after authorizing group2')
            self.status('Sleeping for 10 seconds to allow rule/network'
                        ' to set...')
            time.sleep(10)
            self.status('Attempting to ping group1 instance from group2 '
                        'instance using their private IPs')
            try:
                zone.test_instance_group2.proxy_ssh.verbose = True
                zone.test_instance_group2.proxy_ssh.sys(
                    'ping -c 1 {0}'
                    .format(zone.test_instance_group1.private_ip_address),
                    code=0,verbose=True)
            except:
                self.errormsg('Failed to ping from group2 to group1 instance '
                              'after authorizing the source group2')
                raise
        self.status('Terminating all instances in group2 in order to delete '
                    'security group2')
        tester.ec2.terminate_instances(self.group2_instances)
        self.group2_instances = []
        tester.ec2.delete_group(self.group2)
        self.status('Now confirm that ssh still works for all instances in group1')
        for instance in self.group1_instances:

            instance.sys('echo "Getting hostname from {0}"; hostname'
                         .format(instance.id), code=0)
        self.status('Passed. Group1 ssh working after deleting src group which '
                    'was authorized to group1')

    def test9_ssh_between_instances_same_group_same_zone_public(self):
        """
        Definition:
        For each zone this test will attempt to test ssh between two instances in the same
        security group using the public ips of the instances.
        -Authorize group for ssh access
        -Re-use or create 2 instances within the same security group, same zone
        -For each zone, attempt to ssh to a vm in the same security group same zone
        """
        self.tester.ec2.authorize_group(self.group1, port=22, protocol='tcp', cidr_ip='0.0.0.0/0')
        for zone in self.zones:
            instances =[]
            for instance in self.group1_instances:
                if instance.placement == zone:
                    assert isinstance(instance, EuInstance)
                    instances.append(instance)
            if len(instances) < 2:
                for x in xrange(len(instances), 2):
                    self.test1_create_instance_in_zones_for_security_group1(zones=[zone])
        for zone in self.zones:
            zone_instances = []
            for instance in self.group1_instances:
                if instance.placement == zone:
                    zone_instances.append(instance)
            instance1 = zone_instances[0]
            instance2 = zone_instances[1]
            instance1.ssh.sftp_put(instance1.keypath, 'testkey.pem')
            instance1.sys('chmod 0600 testkey.pem')
            testphrase = "pubsamezone_test_from_instance1_{0}".format(instance1.id)
            testfile = 'testfile.txt'
            instance1.sys("ssh -o StrictHostKeyChecking=no -i testkey.pem root@{0} "
                          "\'echo {1} > {2}; hostname; ifconfig; pwd; ls\'"
                          .format(instance2.ip_address, testphrase, testfile), code=0, timeout=10)
            instance2.sys('hostname; ifconfig; pwd; ls; cat {0} | grep {1}'.format(testfile, testphrase), code=0)

    def test10_ssh_between_instances_same_group_public_different_zone(self):
        """
        Definition:
        If multiple zones are detected, this test will attempt to test ssh between
        two instances in the same security group and accross each zone using the public ips
        of the instances
        -Authorize group for ssh access
        -Re-use or create 2 instances within the same security group, different zone(s)
        -For each zone, attempt to ssh to a vm in the same security group different zone(s)
        """
        if len(self.zones) < 2:
            raise SkipTestException('Skipping multi-zone test, '
                                    'only a single zone found or provided')
        self.tester.ec2.authorize_group(self.group1, port=22, protocol='tcp', cidr_ip='0.0.0.0/0')
        zone_instances = {}
        for zone in self.zones:
            instances =[]
            for instance in self.group1_instances:
                if instance.placement == zone:
                    assert isinstance(instance, EuInstance)
                    instances.append(instance)
            if len(instances) < 1:
                for x in xrange(len(instances), 1):
                    self.test1_create_instance_in_zones_for_security_group1(zones=[zone])
            zone_instances[zone] = instances
        for zone1 in self.zones:
            instance1 = zone_instances[zone1][0]
            instance1.ssh.sftp_put(instance1.keypath, 'testkey.pem')
            instance1.sys('chmod 0600 testkey.pem')
            for zone2 in self.zones:
                if zone != zone2:
                    instance2 = zone_instances[zone2][0]
                    testphrase = "diffpubzone_test_from_instance1_{0}".format(instance1.id)
                    testfile = 'testfile.txt'
                    instance1.sys("ssh -o StrictHostKeyChecking=no -i testkey.pem root@{0} "
                                  "\'echo {1} > {2}; hostname; ifconfig; pwd; ls\'"
                                  .format(instance2.ip_address, testphrase, testfile),
                                  code=0,
                                  timeout=10)
                    instance2.sys('cat {0} | grep {1}'.format(testfile, testphrase), code=0)

    def test11_ssh_between_instances_same_group_same_zone_private(self):
        """
        Definition:
        For each zone this test will attempt to test ssh between two instances in the same
        security group using the private ips of the instances.
        -Authorize group for ssh access
        -Re-use or create 2 instances within the same security group, same zone
        -For each zone, attempt to ssh to a vm in the same security group same zone
        """
        self.tester.ec2.authorize_group(self.group1, port=22, protocol='tcp', cidr_ip='0.0.0.0/0')
        for zone in self.zones:
            instances =[]
            for instance in self.group1_instances:
                if instance.placement == zone:
                    assert isinstance(instance, EuInstance)
                    instances.append(instance)
            if len(instances) < 2:
                for x in xrange(len(instances), 2):
                    self.test1_create_instance_in_zones_for_security_group1(zones=[zone])
        for zone in self.zones:
            zone_instances = []
            for instance in self.group1_instances:
                if instance.placement == zone:
                    zone_instances.append(instance)
            instance1 = zone_instances[0]
            instance2 = zone_instances[1]
            instance1.ssh.sftp_put(instance1.keypath, 'testkey.pem')
            instance1.sys('chmod 0600 testkey.pem')
            testphrase = "hello_from_instance1_{0}".format(instance1.id)
            testfile = 'testfile.txt'
            instance1.sys("ssh -o StrictHostKeyChecking=no -i testkey.pem root@{0} "
                          "\'echo {1} > {2}; hostname; ifconfig; pwd; ls\'"
                          .format(instance2.private_ip_address, testphrase, testfile),
                          code=0,
                          timeout=10)
            instance2.sys('cat {0} | grep {1}'.format(testfile, testphrase), code=0)

    def test12_ssh_between_instances_same_group_private_different_zone(self):
        """
        Definition:
        If multiple zones are detected, this test will attempt to test ssh between
        two instances in the same security group and across each zone using the instances'
        private ip addresses.
        -Authorize group for ssh access
        -Re-use or create 2 instances within the same security group, different zone(s)
        -For each zone, attempt to ssh to a vm in the same security group different zone(s)
        """
        if len(self.zones) < 2:
            raise SkipTestException('Skipping multi-zone test, '
                                    'only a single zone found or provided')
        self.tester.ec2.authorize_group(self.group1, port=22, protocol='tcp', cidr_ip='0.0.0.0/0')
        for zone in self.zones:
            instances =[]
            for instance in self.group1_instances:
                if instance.placement == zone:
                    assert isinstance(instance, EuInstance)
                    instances.append(instance)
            if len(instances) < 1:
                for x in xrange(len(instances), 1):
                    self.test1_create_instance_in_zones_for_security_group1(zones=[zone])
        for zone1 in self.zones:
            zone_instances = []
            for instance in self.group1_instances:
                if instance.placement == zone1:
                    zone_instances.append(instance)
            instance1 = zone_instances[0]
            instance1.ssh.sftp_put(instance1.keypath, 'testkey.pem')
            instance1.sys('chmod 0600 testkey.pem')
            for zone2 in self.zones:
                if zone1 != zone2:
                    zone2_instances = []
                    for instance in self.group1_instances:
                        if instance.placement == zone2:
                            zone2_instances.append(instance)
                    instance2 = zone_instances[0]
                    testphrase = "diffprivzone_test_from_instance1_{0}".format(instance1.id)
                    testfile = 'testfile.txt'
                    instance1.sys("ssh -o StrictHostKeyChecking=no -i testkey.pem root@{0} "
                                  "\'echo {1} > {2}; hostname; ifconfig; pwd; ls\'"
                                  .format(instance2.ip_address, testphrase, testfile),
                                  code=0,
                                  timeout=10)
                    instance2.sys('cat {0} | grep {1}'.format(testfile, testphrase), code=0)

    def test13_ssh_between_instances_diff_group_private_different_zone(self):
        """
        Definition:
        If multiple zones are detected, this test will attempt to test ssh between
        two instances in the same security group and across each zone using the instances'
        private ip addresses.
        -Authorize group for ssh access
        -Re-use or create 2 instances within the same security group, different zone(s)
        -For each zone, attempt to ssh to a vm in the same security group different zone(s)
        """
        if len(self.zones) < 2:
            raise SkipTestException('Skipping multi-zone test, '
                                    'only a single zone found or provided')
        self.tester.ec2.authorize_group(self.group1, port=22, protocol='tcp', cidr_ip='0.0.0.0/0')
        # In case a previous test has deleted group2...
        self.group2 = self.tester.ec2.add_group(self.group2.name)
        self.tester.ec2.authorize_group(self.group2, port=22, protocol='tcp', cidr_ip='0.0.0.0/0')
        for zone in self.zones:
            instance1 = None
            instances =[]
            for instance in self.group1_instances:
                if instance.placement == zone:
                    instance1 = instance
            if not instance1:
                self.test1_create_instance_in_zones_for_security_group1(zones=[zone])
                for instance in self.group1_instances:
                    if instance.placement == zone:
                        instance1 = instance
            instance1.ssh.sftp_put(instance1.keypath, 'testkey.pem')
            instance1.sys('chmod 0600 testkey.pem')
            for zone2 in self.zones:
                instance2 = None
                if zone2 != zone:
                    for instance in self.group2_instances:
                        if instance.placement == zone2:
                            instance2 = instance
                    if not instance2:
                        self.test2_create_instance_in_zones_for_security_group2(zones=[zone2],
                                                                                auto_connect=True)
                        for instance in self.group2_instances:
                            if instance.placement == zone2:
                                instance2 = instance
                    testphrase = "diffprivzone_test_from_instance1_{0}".format(instance1.id)
                    testfile = 'testfile.txt'
                    self.status('Testing instance:{0} zone:{1} --ssh--> instance:{2} zone:{3} '
                                '-- private ip'.format(instance1.id, zone,instance2.id, zone2))
                    instance1.sys("ssh -o StrictHostKeyChecking=no -i testkey.pem root@{0} "
                                  "\'echo {1} > {2}; hostname; ifconfig; pwd; ls\'"
                                  .format(instance2.private_ip_address, testphrase, testfile),
                                  code=0,
                                  timeout=10)
                    instance2.sys('cat {0} | grep {1}'.format(testfile, testphrase), code=0)

    def test14_ssh_between_instances_diff_group_public_different_zone(self):
        """
        Definition:
        If multiple zones are detected, this test will attempt to test ssh between
        two instances in the same security group and across each zone using the instances'
        private ip addresses.
        -Authorize group for ssh access
        -Re-use or create 2 instances within the same security group, different zone(s)
        -For each zone, attempt to ssh to a vm in the same security group different zone(s)
        """
        if len(self.zones) < 2:
            raise SkipTestException('Skipping multi-zone test, '
                                    'only a single zone found or provided')
        self.tester.ec2.authorize_group(self.group1, port=22, protocol='tcp', cidr_ip='0.0.0.0/0')
        # In case a previous test has deleted group2...
        self.group2 = self.tester.ec2.add_group(self.group2.name)
        self.tester.ec2.authorize_group(self.group2, port=22, protocol='tcp', cidr_ip='0.0.0.0/0')
        for zone in self.zones:
            instance1 = None
            instances =[]
            for instance in self.group1_instances:
                if instance.placement == zone:
                    instance1 = instance
            if not instance1:
                self.test1_create_instance_in_zones_for_security_group1(zones=[zone])
                for instance in self.group1_instances:
                    if instance.placement == zone:
                        instance1 = instance
            instance1.ssh.sftp_put(instance1.keypath, 'testkey.pem')
            instance1.sys('chmod 0600 testkey.pem')
            for zone2 in self.zones:
                instance2 = None
                if zone2 != zone:
                    for instance in self.group2_instances:
                        if instance.placement == zone2:
                            instance2 = instance
                    if not instance2:
                        self.test2_create_instance_in_zones_for_security_group2(zones=[zone2],
                                                                                auto_connect=True)
                        for instance in self.group2_instances:
                            if instance.placement == zone2:
                                instance2 = instance
                    testphrase = "diffprivzone_test_from_instance1_{0}".format(instance1.id)
                    testfile = 'testfile.txt'
                    self.status('Testing instance:{0} zone:{1} --ssh--> instance:{2} zone:{3} '
                                '-- private ip'.format(instance1.id, zone,instance2.id, zone2))
                    instance1.sys("ssh -o StrictHostKeyChecking=no -i testkey.pem root@{0} "
                                  "\'echo {1} > {2}; hostname; ifconfig; pwd; ls\'"
                                  .format(instance2.ip_address, testphrase, testfile),
                                  code=0,
                                  timeout=10)
                    instance2.sys('cat {0} | grep {1}'.format(testfile, testphrase), code=0)


    # add revoke may be covered above...?
    def test_revoke_rules(self):
        assert isinstance(self.tester, Eucaops)
        revoke_group = self.tester.ec2.add_group("revoke-group-" + str(int(time.time())))
        self.tester.ec2.authorize_group(revoke_group, port=22)
        for zone in self.zones:
            instance = self.tester.ec2.run_image(image=self.image,
                                                 keypair=self.keypair,
                                                 group=revoke_group,
                                                 zone=zone)[0]
            self.tester.ec2.revoke(revoke_group, port=22)
            self.tester.sleep(60)
            try:
                instance.reset_ssh_connection(timeout=30)
                self.tester.ec2.delete_group(revoke_group)
                raise Exception("Was able to SSH without authorized rule")
            except SSHException, e:
                self.tester.debug("SSH was properly blocked to the instance")
            self.tester.ec2.authorize_group(revoke_group, port=22)
            instance.reset_ssh_connection()
            self.tester.ec2.terminate_instances(instance)
        self.tester.ec2.delete_group(revoke_group)

if __name__ == "__main__":
    testcase = Net_Tests()

    ### Use the list of tests passed from config/command line to determine what subset of tests to run
    ### or use a predefined list

    if testcase.args.tests:
        testlist = testcase.args.tests
        if not isinstance(testlist, list):
            testlist.replace(',',' ')
            testlist = testlist.split()
    else:
        testlist = ['test1_create_instance_in_zones_for_security_group1',
                    'test2_create_instance_in_zones_for_security_group2',
                    'test3_test_ssh_between_instances_in_diff_sec_groups_same_zone',
                    'test4_attempt_unauthorized_ssh_from_test_machine_to_group2',
                    'test5_test_ssh_between_instances_in_same_sec_groups_different_zone',
                    'test7_add_and_revoke_tcp_port_range',
                    'test8_verify_deleting_of_auth_source_group2',
                    'test9_ssh_between_instances_same_group_same_zone_public',
                    'test10_ssh_between_instances_same_group_public_different_zone',
                    'test11_ssh_between_instances_same_group_same_zone_private',
                    'test12_ssh_between_instances_same_group_private_different_zone',
                    'test13_ssh_between_instances_diff_group_private_different_zone',
                    'test14_ssh_between_instances_diff_group_public_different_zone']
        ### Convert test suite methods to EutesterUnitTest objects
    print 'Got test list:' + str(testlist)
    unit_list = []
    for test in testlist:
        unit_list.append(testcase.create_testunit_by_name(test))

    ### Run the EutesterUnitTest objects
    result = testcase.run_test_case_list(unit_list, eof=False, clean_on_exit=True)
    exit(result)




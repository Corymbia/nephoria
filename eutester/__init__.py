#!/usr/bin/python
# -*- coding: utf-8 -*-
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
# Author: vic.iglesias@eucalyptus.com

__version__ = '0.0.10'


from cloud_utils.log_utils.eulogger import Eulogger
from eutester.testcase_utils import TimeoutFunctionException, wait_for_result
import re
import os
import random
import time
import string
import operator
import types
from functools import wraps

class Eutester(object):
    def __init__(self, credpath=None):
        """This class is intended to setup boto connections for the various services that the *ops classes will use.
        :param credpath: Path to a valid eucarc file.
        :param aws_access_key_id: Used in conjuction with aws_secret_access_key allows for creation of connections without needing a credpath.
        :param aws_secret_access_key: Used in conjuction with aws_access_key_id allows for creation of connections without needing a credpath.
        :rtype: :class:`eutester.Eutester` or ``None``
        :returns: A Eutester object with all connections that were able to be created. Currently EC2, S3, IAM, and STS.
        """
        ### Default values for configuration
        self.credpath = credpath
        
        ### Eutester logs
        self.logger = Eulogger(identifier="EUTESTER")
        self.debug = self.logger.log.debug
        self.critical = self.logger.log.critical
        self.info = self.logger.log.info
        
        ### LOGS to keep for printing later
        self.fail_log = []
        self.running_log = self.logger.log

        ### Pull the access and secret keys from the eucarc or use the ones provided to the constructor
        if self.credpath is not None:
            # self.debug("Extracting keys from " + self.credpath)
            self.aws_access_key_id = self.get_access_key()
            self.aws_secret_access_key = self.get_secret_key()
            self.account_id = self.get_account_id()
            self.user_id = self.get_user_id()

    def get_ec2_ip(self):
        """Parse the eucarc for the EC2_URL"""
        ec2_url = self.parse_eucarc("EC2_URL")
        return ec2_url.split("/")[2].split(":")[0]

    def get_ec2_path(self):
        """Parse the eucarc for the EC2_URL"""
        ec2_url = self.parse_eucarc("EC2_URL")
        ec2_path = "/".join(ec2_url.split("/")[3:])
        return ec2_path

    def get_s3_ip(self):
        """Parse the eucarc for the S3_URL"""
        s3_url = self.parse_eucarc("S3_URL")
        return s3_url.split("/")[2].split(":")[0]

    def get_s3_path(self):
        """Parse the eucarc for the S3_URL"""
        s3_url = self.parse_eucarc("S3_URL")
        s3_path = "/".join(s3_url.split("/")[3:])
        return s3_path

    def get_elb_ip(self):
        """Parse the eucarc for the AWS_ELB_URL"""
        elb_url = self.parse_eucarc("AWS_ELB_URL")
        return elb_url.split("/")[2].split(":")[0]

    def get_elb_path(self):
        """Parse the eucarc for the AWS_ELB_URL"""
        elb_url = self.parse_eucarc("AWS_ELB_URL")
        elb_path = "/".join(elb_url.split("/")[3:])
        return elb_path

    def get_as_ip(self):
        """Parse the eucarc for the AWS_AUTO_SCALING_URL"""
        as_url = self.parse_eucarc("AWS_AUTO_SCALING_URL")
        return as_url.split("/")[2].split(":")[0]

    def get_as_path(self):
        """Parse the eucarc for the AWS_AUTO_SCALING_URL"""
        as_url = self.parse_eucarc("AWS_AUTO_SCALING_URL")
        as_path = "/".join(as_url.split("/")[3:])
        return as_path

    def get_iam_ip(self):
        """Parse the eucarc for the EUARE_URL"""
        iam_url = self.parse_eucarc("EUARE_URL")
        return iam_url.split("/")[2].split(":")[0]

    def get_iam_path(self):
        """Parse the eucarc for the EUARE_URL"""
        iam_url = self.parse_eucarc("EUARE_URL")
        iam_path = "/".join(iam_url.split("/")[3:])
        return iam_path

    def get_cfn_ip(self):
        """Parse the eucarc for the AWS_CLOUDFORMATION_URL"""
        cfn_url = self.parse_eucarc("AWS_CLOUDFORMATION_URL")
        return cfn_url.split("/")[2].split(":")[0]

    def get_cfn_path(self):
        """Parse the eucarc for the AWS_CLOUDFORMATION_URL"""
        cfn_url = self.parse_eucarc("AWS_CLOUDFORMATION_URL")
        cfn_path = "/".join(cfn_url.split("/")[3:])
        return cfn_path

    def get_cw_ip(self):
        '''Parse the eucarc for the AWS_CLOUDWATCH_URL'''
        cw_url = self.parse_eucarc('AWS_CLOUDWATCH_URL')
        return cw_url.split('/')[2].split(':')[0]

    def get_cw_path(self):
        """Parse the eucarc for the AWS_CLOUDWATCH_URL"""
        cw_url = self.parse_eucarc("AWS_CLOUDWATCH_URL")
        cw_path = "/".join(cw_url.split("/")[3:])
        return cw_path

    def get_sts_ip(self):
        """Parse the eucarc for the TOKEN_URL"""
        sts_url = self.parse_eucarc("TOKEN_URL")
        return sts_url.split("/")[2].split(":")[0]

    def get_sts_path(self):
        """Parse the eucarc for the TOKEN_URL"""
        sts_url = self.parse_eucarc("TOKEN_URL")
        sts_path = "/".join(sts_url.split("/")[3:])
        return sts_path

    def get_access_key(self):
        if not self.aws_access_key_id:     
            """Parse the eucarc for the EC2_ACCESS_KEY"""
            self.aws_access_key_id = self.parse_eucarc("EC2_ACCESS_KEY")  
        return self.aws_access_key_id 
    
    def get_secret_key(self):
        if not self.aws_secret_access_key: 
            """Parse the eucarc for the EC2_SECRET_KEY"""
            self.aws_secret_access_key = self.parse_eucarc("EC2_SECRET_KEY")
        return self.aws_secret_access_key
    
    def get_account_id(self):
        if not self.account_id:
            """Parse the eucarc for the EC2_ACCOUNT_NUMBER"""
            self.account_id = self.parse_eucarc("EC2_ACCOUNT_NUMBER")
        return self.account_id
    
    def get_user_id(self):
        if not self.user_id:
            self.user_id = self.parse_eucarc("EC2_USER_ID")
        """Parse the eucarc for the EC2_ACCOUNT_NUMBER"""
        return self.user_id 

    def get_port(self):
        """Parse the eucarc for the EC2_ACCOUNT_NUMBER"""
        ec2_url = self.parse_eucarc("EC2_URL")
        return ec2_url.split(':')[1].split("/")[0]

    def parse_eucarc(self, field):
        if self.credpath is None:
            raise ValueError('Credpath has not been set yet. '
                             'Please set credpath or provide '
                             'configuration file')
        with open( self.credpath + "/eucarc") as eucarc:
            for line in eucarc.readlines():
                if re.search(field, line):
                    return line.split("=")[1].strip().strip("'")
            raise Exception("Unable to find " +  field + " id in eucarc")
    
    def handle_timeout(self, signum, frame): 
        raise TimeoutFunctionException()

    def found(self, command, regex):
        """ Returns a Boolean of whether the result of the command contains the regex
        """
        result = self.local(command)
        for line in result:
            found = re.search(regex,line)
            if found:
                return True
        return False

    def ping(self, address, poll_count = 10):
        """
        Ping an IP and poll_count times (Default = 10)
        address      Hostname to ping
        poll_count   The amount of times to try to ping the hostname iwth 2 second gaps in between
        """
        return net_utils.ping(address, poll_count = 10)

    def scan_port_range(self, ip, start, stop, timeout=1, tcp=True):
        '''
        Attempts to connect to ports, returns list of ports which accepted a connection
        '''
        return net_utils.scan_port_range(ip, start, stop, timeout=1, tcp=True)

    def test_port_status(self,
                         ip,
                         port,
                         timeout=5,
                         tcp=True,
                         recv_size=0,
                         send_buf=None,
                         verbose=True):
        '''
        Attempts to connect to tcp port at ip:port within timeout seconds
        '''
        return net_utils.test_port_status(ip,
                                          port,
                                          timeout=5,
                                          tcp=True,
                                          recv_size=0,
                                          send_buf=None,
                                          verbose=True)

    def grep(self, string, list):
        """ Remove the strings from the list that do not match the regex string"""
        expr = re.compile(string)
        return filter(expr.search,list)

    def diff(self, list1, list2):
        """Return the diff of the two lists"""
        return list(set(list1)-set(list2))
    
    def fail(self, message):
        self.critical(message)
        #self.fail_log.append(message)
        self.fail_count += 1
        if self.exit_on_fail == 1:
            raise Exception("Test step failed: "+str(message))
        else:
            return 0 
    
    def clear_fail_log(self):
        self.fail_log = []
        return
    
    def get_exectuion_time(self):
        """Returns the total execution time since the instantiation of the Eutester object"""
        return time.time() - self.start_time
       
    def clear_fail_count(self):
        """ The counter for keeping track of all the errors """
        self.fail_count = 0
        
    def sleep(self, seconds=1):
        """Convinience function for time.sleep()"""
        self.debug("Sleeping for " + str(seconds) + " seconds")
        time.sleep(seconds)

    @staticmethod
    def render_file_template(src, dest, **kwargs):
        return file_utils.render_file_template(src, dest, **kwargs)

    def id_generator(self, size=6, chars=None):
        """Returns a string of size with random charachters from the chars array.
             size    Size of string to return
             chars   Array of characters to use in generation of the string
        """
        chars = chars or (string.ascii_uppercase + string.ascii_lowercase  + string.digits)
        return ''.join(random.choice(chars) for x in range(size))

    @staticmethod
    def get_terminal_size():
        '''
        Attempts to get terminal size. Currently only Linux.
        returns (height, width)
        '''
        return log_utils.get_terminal_size()

    @staticmethod
    def get_line(length=None):
        line = ""
        if not length:
            try:
                length = Eutester.get_terminal_size()[1]
                if length <= 1:
                    length = 80
            except:
                length = 80
        for x in xrange(0,int(length)):
            line += "-"
            return "\n" + line + "\n"

    @classmethod
    def printinfo(cls, func):
        '''
        Decorator to print method positional and keyword args when decorated method is called
        usage:
        @printinfo
        def myfunction(self, arg1, arg2, kwarg1=defaultval):
            stuff = dostuff(arg1, arg2, kwarg1)
            return stuff
        When the method is run it will produce debug output showing info as to how the
        method was called, example:
        
        myfunction(arg1=123, arg2='abc', kwarg='words)
        
        2013-02-07 14:46:58,928] [DEBUG]:(mydir/myfile.py:1234) - Starting method: myfunction()
        2013-02-07 14:46:58,928] [DEBUG]:---> myfunction(self, arg1=123, arg2=abc, kwarg='words')
        '''

        @wraps(func)
        def methdecor(*func_args, **func_kwargs):
            _args_dict = {} # If method has this kwarg populate with args here
            try:
                defaults = func.func_defaults
                kw_count = len(defaults or [])
                selfobj = None
                arg_count = func.func_code.co_argcount - kw_count
                var_names = func.func_code.co_varnames[:func.func_code.co_argcount]
                arg_names = var_names[:arg_count]
                kw_names =  var_names[arg_count:func.func_code.co_argcount]
                kw_defaults = {}
                for kw_name in kw_names: 
                    kw_defaults[kw_name] = defaults[kw_names.index(kw_name)]
                arg_string=''
                # If the underlying method is using a special kwarg named
                # '_args_dict' then provide all the args & kwargs it was
                # called with in that dict for inspection with that method
                if 'self' in var_names and len(func_args) <= 1:
                    func_args_empty = True
                else:
                    func_args_empty = False
                if (not func_args_empty or func_kwargs) and \
                                '_args_dict' in kw_names:
                    if not '_args_dict' in func_kwargs or \
                            not func_kwargs['_args_dict']:
                        func_kwargs['_args_dict'] = {'args':func_args,
                                                     'kwargs':func_kwargs}
                # iterate on func_args instead of arg_names to make sure we pull out
                # self object if present
                for count, arg in enumerate(func_args):
                    if count == 0 and var_names[0] == 'self': #and if hasattr(arg, func.func_name):
                        #self was passed don't print obj addr, and save obj for later
                        arg_string += 'self'
                        selfobj = arg
                    elif count >= arg_count:
                        #Handle case where kw args are passed w/o key word as a positional arg add 
                        #Add it to the kw_defaults so it gets printed later
                        kw_defaults[var_names[count]] = arg
                    else:
                        #This is a positional arg so grab name from arg_names list
                        arg_string += ', '
                        arg_string += str(arg_names[count])+'='+str(arg)
                kw_string = ""
                for kw in kw_names:
                    kw_string += ', '+str(kw)+'='
                    if kw in func_kwargs:
                        kw_string += str(func_kwargs[kw])
                    else:
                        kw_string += str(kw_defaults[kw])
                debugstring = '\n--->(' + str(os.path.basename(func.func_code.co_filename)) + \
                              ":" + str(func.func_code.co_firstlineno) + ")Starting method: " + \
                              str(func.func_name) + '(' + arg_string + kw_string + ')'
                debugmethod = None
                if selfobj and hasattr(selfobj,'debug'):
                    debug = getattr(selfobj, 'debug')
                    if isinstance(debug, types.MethodType):
                        debugmethod = debug
                if debugmethod:    
                    debugmethod(debugstring)
                else:
                    print debugstring
            except Exception, e:
                print Eutester.get_traceback()
                print 'printinfo method decorator error:'+str(e)
            return func(*func_args, **func_kwargs)
        return methdecor

    def wait_for_result(self,
                        callback,
                        result,
                        timeout=60,
                        poll_wait=10,
                        oper=operator.eq,
                        allowed_exception_types=None,
                        debug_method=None,
                        **callback_kwargs):
        """
        Repeatedly run and wait for the provided callback to return the expected result,
        or timeout

        :param callback: A function/method to run and monitor the result of
        :param result: result from the call back provided that we are looking for
        :param poll_wait:Time to wait between callback executions
        :param timeout: Time in seconds to wait before timing out and returning failure
        :param allowed_exception_types: list of exception classes that can be caught and allow
                                        the wait_for_result operation to continue
        :param oper: operator obj used to evaluate 'result' against callback's
                     result. ie operator.eq, operator.ne, etc..
        :param debug_method: optional method to use when writing debug messages
        :param callback_kwargs: optional kwargs to be provided to 'callback' when its executed
        :return: result upon success
        :raise: TimeoutFunctionException when instance does not enter proper state
        """
        return wait_for_result(callback,
                               result,
                               timeout=60,
                               poll_wait=10,
                               oper=operator.eq,
                               allowed_exception_types=None,
                               debug_method=None,
                               **callback_kwargs)
    @classmethod
    def get_traceback(cls):
        '''
        Returns a string buffer with traceback, to be used for debug/info purposes. 
        '''
        return log_utils.get_traceback()
    
    def __str__(self):
        return '{0}'.format(self.__class__)



    



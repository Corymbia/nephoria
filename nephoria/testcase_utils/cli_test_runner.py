"""
This is the base class for any test case to be included in the Eutester repo. It should include any
functionality that we expected to be repeated in most of the test cases that will be written.
This harness is primarily intended to help provide a common means of running and reporting
'system tests' (vs unit tests).
For the purposes of this module, a 'system' focused test suite is the sum of a what would
otherwise be many 'unit tests' in order to produce an end to end flow that might mimic a
users's experience and test interactions of the system.
This module is also intended to provide the most commonly shared test attributes amongst the
existing tests when this was written:
    cli options/arguments,
    logging to stdout, err and a file provided via cli arg,
    option to specify a portions or a single unit by providing a list of units to be looked up
        by name, method, etc..
    gathered/summary of results and metrics,
    sharing of test artifacts (to save time over suite execution),
    ability to skip tests based on dependencies such as a previous test unit's status, etc..
    ability to share/extend testcase classes to build upon other test case classes/suites.
    basic config file parsing (arguments in file are merged with cli args)



Currently included:
 - Debug method
 - Allow parameterized test cases
 - Method to run test case
 - Run a list of test cases
 - Start, end and current status messages
 - Enum class for possible test results

Necessary to work on:
 - Argument parsing
 - Metric tracking (need to define what metrics we want
 - Standardized result summary
 - Logging standardization
 - Use docstring as description for test case
 - Standardized setUp and tearDown that provides useful/necessary cloud resources
  (ie group, keypair, image)


##################################################################################################
#                       Sample test and output:                                                  #
##################################################################################################
See README.md for more info

"""

import unittest
import inspect
import time
import gc
import argparse
import re
import sys
import os
import types
import traceback
import random
import string
from collections import OrderedDict
from decorator import decorator
from functools import wraps
from prettytable import PrettyTable
from cloud_utils.log_utils.eulogger import Eulogger
from cloud_utils.log_utils import markup, ForegroundColor, BackGroundColor, TextStyle
from cloud_utils.log_utils import red, green, blue, yellow, cyan, get_traceback, get_terminal_size
from nephoria.testcase_utils.euconfig import EuConfig
import StringIO
import copy


def _get_method_args_kwargs(method):
    args = []
    kwargdict = OrderedDict()
    spec = inspect.getargspec(method)
    if spec.defaults:
        kwarg_index = len(spec.args) - len(spec.defaults)
        args = spec.args[0:kwarg_index]
        kwargs = spec.args[kwarg_index:]
        for value in spec.defaults:
            kwargdict[kwargs.pop(0)] = value
    else:
        args = spec.args
    return args, kwargdict

def RegisterTestCase(description=None, category=[], test_type=None, testids=[], misc={}):
    def wrapped(fn):
        ars, kws = _get_method_args_kwargs(fn)
        @wraps(fn)
        def wrapped_f(*args, **kwargs):
            return fn(*args, **kwargs)
        wrapped_f.description = description or wrapped_f.__doc__
        wrapped_f.category = category
        wrapped_f.misc = misc
        wrapped_f.test_type = test_type
        wrapped_f
        return wrapped_f
    return wrapped



class TestResult():
    '''
    standardized test results
    '''
    not_run = "NOT_RUN"
    passed = "PASSED"
    failed = "FAILED"

class TestUnit():
    '''
    Description: Convenience class to run wrap individual methods, and run and store and access
    results.

    type method: method
    param method: The underlying method for this object to wrap, run and provide information on

    type args: list of arguments
    param args: the arguments to be fed to the given 'method'

    type eof: boolean
    param eof: boolean to indicate whether a failure while running the given 'method' should end t
    he test case execution.
    '''
    def __init__(self, method, html_anchors=False, test_unit_name=None, test_unit_description=None,
                 *args, **kwargs):
        if not hasattr(method, '__call__'):
            raise ValueError('TestUnit method is not callable: "{0}"'.format(method))
        self.method = method
        self.method_possible_args = CliTestRunner.get_meth_arg_names(self.method)
        self.args = args
        self.kwargs = kwargs
        self.name = test_unit_name or str(method.__name__)
        self.result = TestResult.not_run
        self.time_to_run = 0
        #if self.kwargs.get('html_anchors', False):
        if html_anchors:
            self.anchor_id = str(str(time.ctime()) + self.name + "_" +
                                 str(''.join(random.choice(string.ascii_uppercase +
                                     string.ascii_lowercase +
                                     string.digits) for x in range(3))) + "_").replace(" ", "_")
            self.error_anchor_id = "ERROR_" + self.anchor_id
        self.description = test_unit_description
        if self.description is None:
            self.description = self.get_test_method_description()
        self.eof = False
        self.error = ""
        print "Creating testunit:" + str(self.name) + ", args:"
        for count, thing in enumerate(args):
            print '{0}. {1}'.format(count, thing)
        for name, value in kwargs.items():
            print '{0} = {1}'.format(name, value)

    @classmethod
    def create_testcase_from_method(cls, method, eof=False, *args, **kwargs):
        '''
        Description: Creates a EutesterTestUnit object from a method and set of arguments to be
        fed to that method

        type method: method
        param method: The underlying method for this object to wrap, run and provide information on

        type args: list of arguments
        param args: the arguments to be fed to the given 'method'
        '''
        testunit = TestUnit(method, args, kwargs)
        testunit.eof = eof
        return testunit

    def set_kwarg(self, kwarg, val):
        self.kwargs[kwarg] = val

    def get_test_method_description(self):
        '''
        Description:
        Attempts to derive test unit description for the registered test method.
        Keys off the string "Description:" preceded by any amount of white space and ending with
        either a blank line or the string "EndDescription". This is used in debug output when
        providing info to the user as to the method being run as a testunit's
        intention/description.
        '''
        desc = "\nMETHOD:" + str(self.name) + ", TEST DESCRIPTION:\n"
        ret = []
        try:
            doc = str(self.method.__doc__)
            if not doc:
                try:
                    desc = desc + "\n".join(self.method.im_func.func_doc.title().splitlines())
                except:
                    pass
                return desc

            for line in doc.splitlines():
                line = line.lstrip().rstrip()
                if re.search('^\s+:', line):
                    break
                ret.append(line)
        except Exception, e:
            print('get_test_method_description: error' + str(e))
        if ret:
            desc = desc + "\n".join(ret)
        return desc

    def run(self, eof=None):
        '''
        Description: Wrapper which attempts to run self.method and handle failures, record time.
        '''
        if eof is None:
            eof = self.eof
        for count, value in enumerate(self.args):
            print 'ARG:{0}. {1}'.format(count, value)
        for key, value in self.kwargs.items():
            print 'KWARG:{0} = {1}'.format(key, value)
        start = time.time()
        args = self.args or []
        kwargs = self.kwargs or {}
        try:
            ret = self.method(*args, **kwargs)
            self.result = TestResult.passed
            return ret
        except SkipTestException, se:
            print red("TESTUNIT SKIPPED:" + str(self.name) + "\n" + str(se))
            self.error = str(se)
            self.result = TestResult.not_run
        except Exception, e:
            buf = '\nTESTUNIT FAILED: ' + self.name
            if self.kwargs.get('html_anchors', False):
                buf += "<font color=red> Error in test unit '" + self.name + "':\n"
            if self.kwargs.get('html_anchors', False):
                buf += ' </font>'
                print '<a name="' + str(self.error_anchor_id) + '"></a>'
            print red("{0}\n".format(get_traceback()))
            self.error = str(e)
            self.result = TestResult.failed
            if eof:
                raise e
            else:
                pass
        finally:
            self.time_to_run = int(time.time() - start)


class CliTestRunner(object):
    # List of dicts/kwargs to be used to fed to
    # cli parser.add_argument() to build additional cli args.
    _DEFAULT_CLI_ARGS = {
        'password': {'args': ["--password"],
                     'kwargs': {"help": "Password to use for machine root ssh access",
                                "default": None}},
        'emi': {'args': ["--emi"],
                'kwargs': {"help": "pre-installed emi id which to execute these "
                                   "nephoria_unit_tests against",
                           "default": None}},
        'zone': {'args': ["--zone"],
                 'kwargs': {"help": "Zone to use in this test",
                            "default": None}},
        'vmtype': {'args': ["--vmtype"],
                   'kwargs': {"help": "Virtual Machine Type to use in this test",
                              "default": "c1.medium"}},
        'clc': {'args': ["--clc"],
                'kwargs': {"help": "Address of Machine hosting CLC services",
                           "default": None}},
        'log_level': {'args': ["--log-level"],
                      'kwargs': {"help": "log level for stdout logging",
                                 "default": 'DEBUG'}},
        'test_account': {'args': ['--test-account'],
                      'kwargs': {"help": "Cloud account name to use",
                                 "default": "testrunner"}},
        'test_user': {'args': ['--test-user'],
                      'kwargs': {"help": "Cloud user name to use",
                                 "default": "admin"}},
        'log_file': {'args': ['--log-file'],
                     'kwargs': {"help": "file path to log to (in addition to stdout",
                                "default": None}},
        'log_file_level': {'args': ['--log-file-level'],
                          'kwargs': {"help": "log level to use when logging to '--log-file'",
                                     "default": "DEBUG"}},
        'test_list': {'args': ['--test-list'],
                      'kwargs': {"help": "comma or space delimited list of test names to run",
                                 "default": None}},
        'config_file': {'args': ['--config-file'],
                      'kwargs': {"help": "Test Config file path",
                                 "default": None}},
    }


    _CLI_DESCRIPTION = "CLI TEST RUNNER"


    def __init__(self, name=None, description=None, **kwargs):
        self.name = name or self.__class__.__name__
        # create parser
        self.parser = argparse.ArgumentParser(prog=self.name, description=self._CLI_DESCRIPTION)
        # create cli options from class dict
        for argname, arg_dict in self._DEFAULT_CLI_ARGS.iteritems():
            cli_args = arg_dict.get('args')
            cli_kwargs = arg_dict.get('kwargs')
            self.parser.add_argument(*cli_args, **cli_kwargs)
        # Combine CLI provided args with any values found in a config file (if provided)
        self.get_args()
        self._testlist = getattr(self.args, 'test_list', None)
        log_level = getattr(self.args, 'log_level', 'INFO')
        log_file = getattr(self.args, 'log_file', None)
        log_file_level = getattr(self.args, 'log_file_level', "DEBUG")
        self.html_anchors = False
        # Allow __init__ to get args from __init__'s kwargs or through command line parser...
        for kw in kwargs:
            print 'Setting kwarg:'+str(kw)+" to "+str(kwargs[kw])
            self.set_arg(kw ,kwargs[kw])
        print dir(self.args)
        self.log = Eulogger(identifier=self.name, stdout_level=log_level,
                               logfile=log_file, logfile_level=log_file_level)
        self._term_width = 110
        height, width = get_terminal_size()
        if width < self._term_width:
            self._term_width = width
        self.show_args()
        self.show_self()


    def run_test_list_by_name(self, list, eof=None):
        unit_list = []
        for test in list:
            unit_list.append(self.create_testunit_by_name(test))

        # Run the EutesterUnitTest objects
        return self.run_test_case_list(unit_list, eof=eof)

    def create_testunit_from_method(self, method, *args, **kwargs):
        '''
        Description: Convenience method calling EutesterTestUnit.
                     Creates a EutesterTestUnit object from a method and set of arguments to be
                     fed to that method

        :type method: method
        :param method: The underlying method for this object to wrap, run and provide
                       information on

        :type eof: boolean
        :param eof: Boolean to indicate whether this testunit should cause a test list to end of
                    failure

        :type autoarg: boolean
        :param autoarg: Boolean to indicate whether to autopopulate this testunit with values from
                        global testcase.args

        :type args: list of positional arguments
        :param args: the positional arguments to be fed to the given testunit 'method'

        :type kwargs: list of keyword arguements
        :param kwargs: list of keyword

        :rtype: EutesterTestUnit
        :returns: EutesterTestUnit object
        '''
        eof = False
        autoarg = True
        methvars = self.get_meth_arg_names(method)
        # Pull out value relative to this method, leave in any that are intended to be passed
        # through
        if 'autoarg' in kwargs:
            if 'autoarg' in methvars:
                autoarg = kwargs['autoarg']
            else:
                autoarg = kwargs.pop('autoarg')
        if 'eof' in kwargs:
            if 'eof' in methvars:
                eof = kwargs['eof']
            else:
                eof = kwargs.pop('eof')
        # Only pass the arg if we need it otherwise it will print with all methods/testunits
        if self.html_anchors:
            testunit = TestUnit(method, *args, html_anchors=self.html_anchors,
                                        **kwargs)
        else:
            testunit = TestUnit(method, *args, **kwargs)
        testunit.eof = eof
        # if autoarg, auto populate testunit arguements from local testcase.args namespace values
        if autoarg:
            self.populate_testunit_with_args(testunit)
        return testunit

    def status(self, msg, markups=[32]):
        '''
        Description: Convenience method to format debug output

        :type msg: string
        :param msg: The string to be formated and printed via self.debug

        :param color: asci markup color to use, or None
        '''
        if markups:
            msg = markup(msg, markups=markups)
        pt = PrettyTable(['status'])
        pt.header = False
        pt.align = 'l'
        pt.padding_width = 0
        pt.vrules = 2
        pt.add_row([msg])
        self.log.info("\n{0}\n".format(pt))


    def startmsg(self, msg=""):
        self.status(msg, markups=[ForegroundColor.WHITE, BackGroundColor.BG_BLUE, TextStyle.BOLD])

    def endsuccess(self, msg=""):
        msg = "- END SUCCESS - {0}".format(msg).center(self._term_width)
        self.status(msg, markups=[ForegroundColor.WHITE, BackGroundColor.BG_GREEN, TextStyle.BOLD])
        return msg

    def errormsg(self, msg=""):
        msg = "- ERROR - " + msg
        self.status(msg, markups=[ForegroundColor.RED, TextStyle.BOLD])
        return msg

    def endfailure(self, msg=""):
        msg = "- END FAILURE - {0}".format(msg).center(self._term_width)
        self.status(msg, markups=[ForegroundColor.WHITE, BackGroundColor.BG_RED, TextStyle.BOLD])
        return msg

    def endnotrun(self, msg=""):
        msg = "- END NOT RUN - {0}".format(msg).center(self._term_width)
        self.status(msg, markups=[ForegroundColor.WHITE, BackGroundColor.BG_MAGENTA,
                                  TextStyle.BOLD])
        return msg

    def resultdefault(self, msg, printout=True):
        msg = markup(msg, markups=[ForegroundColor.BLUE, BackGroundColor.BG_WHITE])
        if printout:
            self.log.debug(msg)
        return msg

    def resultfail(self, msg, printout=True):
        msg = markup(msg, markups=[ForegroundColor.RED, BackGroundColor.BG_WHITE])
        if printout:
            self.log.debug(msg)
        return msg

    def resulterr(self, msg, printout=True):
        msg = red(msg)
        if printout:
            self.log.debug(msg)
        return msg

    def get_pretty_args(self, testunit):
        '''
        Description: Returns a string buf containing formated arg:value for printing later

        :type: testunit: Eutestcase.eutestertestunit object
        :param: testunit: A testunit object for which the namespace args will be used

        :rtype: string
        :returns: formated string containing args and their values.
        '''
        buf = "\nEnd on Failure:" + str(testunit.eof)
        buf += "\nPassing ARGS:"
        if not testunit.args and not testunit.kwargs:
            buf += '\"\"\n'
        else:
            buf += "\n---------------------\n"
            varnames = self.get_meth_arg_names(testunit.method)
            if testunit.args:
                for count, arg in enumerate(testunit.args):
                    buf += str(varnames[count + 1]) + " : " + str(arg) + "\n"
            if testunit.kwargs:
                for key in testunit.kwargs:
                    buf += str(key) + " : " + str(testunit.kwargs[key]) + "\n"
            buf += "---------------------\n"
        return buf

    def run_test_case_list(self, testlist=None, eof=False, clean_on_exit=True, printresults=True):
        '''
        Desscription: wrapper to execute a list of ebsTestCase objects

        :type list: list
        :param list: list of EutesterTestUnit objects to be run

        :type eof: boolean
        :param eof: Flag to indicate whether run_test_case_list should exit on any failures.
                    If this is set to False it will exit only when a given EutesterTestUnit
                    fails and has it's eof flag set to True.

        :type clean_on_exit: boolean
        :param clean_on_exit: Flag to indicate if clean_on_exit should be ran at end of test
                              list execution.

        :type printresults: boolean
        :param printresults: Flag to indicate whether or not to print a summary of results upon
                             run_test_case_list completion.

        :rtype: integer
        :returns: integer exit code to represent pass/fail of the list executed.
        '''
        if testlist is None:
            def key(text):
                return [(int(c) if c.isdigit() else c) for c in re.split('(\d+)', text)]
            testlist = []
            # Get all the local methods which being with the work 'test' and run those.
            attr_names = []
            for name in dir(self):
                if name.startswith('test'):
                    attr_names.append(name)
            for name in sorted(attr_names, key=key):
                attr = getattr(self, name, None)
                if hasattr(attr, '__call__'):
                    testlist.append(self.create_testunit_from_method(method=attr,
                                                                     test_unit_name=name))
        self._testlist = testlist
        if not self._testlist:
            self.log.warning('No tests were provided or found to run?')
            return None
        start = time.time()
        tests_ran = 0
        test_count = len(self._testlist)
        try:
            for test in self._testlist:
                tests_ran += 1
                self.print_test_unit_startmsg(test)
                try:
                    test.run(eof=eof or test.eof)
                except Exception, e:
                    self.log.debug('Testcase:' + str(test.name) + ' error:' + str(e))
                    if eof or (not eof and test.eof):
                        self.endfailure(' TEST:"{0}" COMPLETE'.format(test.name))
                        raise e
                    else:
                        self.endfailure(' TEST:"{0}" COMPLETE '.format(test.name))
                else:
                    if test.result == TestResult.failed:
                        self.endfailure(' TEST:"{0}" COMPLETE'.format(test.name))
                    elif test.result == TestResult.not_run:
                        self.endnotrun(' TEST:"{0}" COMPLETE'.format(test.name))
                    elif test.result == TestResult.passed:
                        self.endsuccess(' TEST:"{0}" COMPLETE'.format(test.name))
                    else:
                        self.log.info(' TEST:"{0}" COMPLETE'.format(test.name))
                self.log.debug(self.print_test_list_short_stats(self._testlist))

        finally:
            elapsed = int(time.time() - start)
            msgout = "RUN TEST CASE LIST DONE:\n"
            msgout += "Ran " + str(tests_ran) + "/" + str(test_count) + " nephoria_unit_tests in " + str(
                elapsed) + " seconds\n"
            if printresults:
                try:
                    self.log.debug("Printing pre-cleanup results:")
                    msgout += self.print_test_list_results(testlist=self._testlist, printout=False)
                    self.status(msgout)
                except:
                    pass
            try:
                if clean_on_exit:
                    cleanunit = self.create_testunit_from_method(self.clean_method)
                    self._testlist.append(cleanunit)
                    try:
                        self.print_test_unit_startmsg(cleanunit)
                        cleanunit.run()
                    except Exception, e:
                        out = StringIO.StringIO()
                        traceback.print_exception(*sys.exc_info(), file=out)
                        out.seek(0)
                        self.log.debug("Failure in cleanup: " + str(e) + "\n" + out.read())
                    if printresults:
                        msgout = self.print_test_list_results(testlist=self._testlist,
                                                              printout=False)
                        self.status(msgout)
            except:
                pass
            self._testlist = copy.copy(self._testlist)
            passed = 0
            failed = 0
            not_run = 0
            for test in self._testlist:
                if test.result == TestResult.passed:
                    passed += 1
                if test.result == TestResult.failed:
                    failed += 1
                if test.result == TestResult.not_run:
                    not_run += 1
            total = passed + failed + not_run
            print "passed:" + str(passed) + " failed:" + str(failed) + " not_run:" + str(
                not_run) + " total:" + str(total)
            if failed:
                return (1)
            else:
                return (0)

    def print_test_unit_startmsg(self, test):
        startbuf = ''
        if self.html_anchors:
            link = '<a name="' + str(test.anchor_id) + '"></a>\n'
            startbuf += '<div id="myDiv" name="myDiv" title="Example Div Element" style="color: ' \
                        '#0900C4; font: Helvetica 12pt;border: 1px solid black;">'
            startbuf += str(link)
        pt = PrettyTable(['HEADER'])
        pt.header = False
        pt.align = 'l'
        buf = "STARTING TESTUNIT: {0}".format(test.name).ljust(self._term_width)
        argbuf = self.get_pretty_args(test)
        buf += str(test.description) + str(argbuf)
        buf += 'Running list method: "' + str(
            self.format_testunit_method_arg_values(test)) + '"'
        pt.add_row([buf])
        startbuf += markup(pt, markups=[ForegroundColor.WHITE, BackGroundColor.BG_BLUE])
        if self.html_anchors:
            startbuf += '\n </div>'
        self.status(startbuf)

    def has_arg(self, arg):
        '''
        Description: If arg is present in local testcase args namespace, will
        return True, else False

        :type arg: string
        :param arg: string name of arg to check for.

        :rtype: boolean
        :returns: True if arg is present, false if not
        '''
        arg = str(arg)
        if hasattr(self, 'args'):
            if self.args and (arg in self.args):
                return True
        return False

    def get_arg(self, arg):
        '''
        Description: Fetchs the value of an arg within the local testcase args namespace.
        If the arg does not exist, None will be returned.

        :type arg: string
        :param arg: string name of arg to get.

        :rtype: value
        :returns: Value of arguement given, or None if not found
        '''
        if self.has_arg(arg):
            return getattr(self.args, str(arg))
        return None

    def add_arg(self, arg, value):
        '''
        Description: Adds an arg 'arg'  within the local testcase args namespace and assigns
                     it 'value'.
        If arg exists already in testcase.args, then an exception will be raised.

        :type arg: string
        :param arg: string name of arg to set.

        :type value: value
        :param value: value to set arg to
        '''
        if self.has_arg(arg):
            raise Exception("Arg" + str(arg) + 'already exists in args')
        else:
            self.args.__setattr__(arg, value)

    def set_arg(self, arg, value):
        '''
        Description: Sets an arg 'arg'  within the local testcase args namespace to 'value'.
        If arg does not exist in testcase.args, then it will be created.

        :type arg: string
        :param arg: string name of arg to set.

        :type value: value
        :param value: value to set arg to
        '''
        if self.has_arg(arg):
            new = argparse.Namespace()
            for val in self.args._get_kwargs():
                if arg != val[0]:
                    new.__setattr__(val[0], val[1])
            new.__setattr__(arg, value)
            self.args = new
        else:
            self.args.__setattr__(arg, value)

    def clean_method(self):
        raise Exception("Clean_method was not implemented. Was run_list using clean_on_exit?")

    def print_test_list_results(self, testlist=None, printout=True, printmethod=None):
        '''
        Description: Prints a formated list of results for a list of EutesterTestUnits

        :type testlist: list
        :param testlist: list of EutesterTestUnits

        :type printout: boolean
        :param printout: boolean to flag whether to print using printmethod or self.debug,
                         or to return a string buffer representing the results outputq

        :type printmethod: method
        :param printmethod: method to use for printing test result output. Default is self.debug
        '''
        main_header = yellow('TEST RESULTS FOR "{0}"'.format(self.name), bold=True)
        if testlist is None:
            testlist = self._testlist
        if not testlist:
            raise Exception("print_test_list_results, error: No Test list provided")
        printmethod = printmethod or self.log.info
        printmethod("Test list results for testcase:" + str(self.name))
        main_pt = PrettyTable([main_header])
        main_pt.align = 'l'
        main_pt.vrules = 2
        main_pt.hrules = 1

        for testunit in testlist:
            # Ascii mark up errors using pmethod() so errors are in bold/red, etc...
            if testunit.result != TestResult.passed:
                markups=[ForegroundColor.RED, BackGroundColor.BG_WHITE]
            else:
                markups=[ForegroundColor.BLUE, BackGroundColor.BG_WHITE]

            term_height, term_width = get_terminal_size()
            if term_width > self._term_width:
                term_width = self._term_width
            key_width = 10
            val_width = term_width - key_width - 6
            headers = ['KEY'.ljust(key_width, "-"), 'VALUE'.ljust(val_width, "-")]
            pt = PrettyTable(headers)
            pt.max_width[headers[0]] = key_width
            pt.max_width[headers[1]] = val_width
            pt.header = False
            pt.align = 'l'
            pt.vrules = 1
            pt.hrules = 2
            test_arg_string = self.format_testunit_method_arg_values(testunit)
            error_summary = None
            # Print additional line showing error in the failed case...
            if testunit.result == TestResult.failed:
                error_summary = "ERROR:({0})"\
                    .format("\n".join(str(testunit.error).splitlines()[0:3]))

            if testunit.result == TestResult.not_run:
                error_summary = 'NOT_RUN ({0}:{1})'\
                    .format(testunit.name, "\n".join(str(testunit.error).splitlines()[0:3]))
            pt.add_row(['RESULT:', str(testunit.result).ljust(val_width)])
            pt.add_row(['TEST NAME', testunit.name])
            pt.add_row(['TIME:', testunit.time_to_run])
            pt.add_row(['TEST ARGS:', test_arg_string])
            pt.add_row(['OUTPUT:', error_summary])
            main_pt.add_row([markup(pt, markups=markups)])

        main_pt.add_row(["\n{0}\n".format(self.print_test_list_short_stats(testlist))])
        if printout:
            printmethod("\n{0}\n".format(main_pt))
        else:
            return main_pt

    def print_test_list_short_stats(self, list, printmethod=None):
        results = {}
        total = 0
        elapsed = 0
        # initialize a dict containing all the possible defined test results
        for result_string in dir(TestResult)[2:]:
            results[getattr(TestResult, result_string)] = 0
        # increment values in results dict based upon result of each testunit in list
        try:
            for testunit in list:
                total += 1
                elapsed += testunit.time_to_run
                results[testunit.result] += 1
        except:
            print results
            raise
        # Create tables with results summaries
        headers = ['TOTAL']
        results_row = [total]
        for field in results:
            headers.append(field.upper())
            results_row.append(results[field])
        headers.append('ELAPSED')
        results_row.append(elapsed)
        pt = PrettyTable(headers)
        pt.vrules = 2
        pt.add_row(results_row)
        main_header = yellow('LATEST RESULTS FOR: "{0}"'.format(self.name), bold=True)
        main_pt = PrettyTable([main_header])
        main_pt.align = 'l'
        main_pt.padding_width = 0
        main_pt.border = False
        main_pt.add_row([str(pt)])
        if printmethod:
            printmethod(main_pt.get_string())
        return "\n{0}\n".format(main_pt)

    @classmethod
    def get_testunit_method_arg_dict(cls, testunit):
        argdict = {}
        spec = inspect.getargspec(testunit.method)
        if isinstance(testunit.method, types.FunctionType):
            argnames = spec.args
        else:
            argnames = spec.args[1:len(spec.args)]
        defaults = spec.defaults or []
        # Initialize the return dict
        for argname in argnames:
            argdict[argname] = '<!None!>'
        # Set the default values of the testunits method
        for x in xrange(0, len(defaults)):
            argdict[argnames.pop()] = defaults[len(defaults) - x - 1]
        # Then overwrite those with the testunits kwargs values
        for kwarg in testunit.kwargs:
            argdict[kwarg] = testunit.kwargs[kwarg]
        # then add the positional args in if they apply...
        for count, value in enumerate(testunit.args):
            argdict[argnames[count]] = value
        return argdict

    @classmethod
    def format_testunit_method_arg_values(cls, testunit):
        buf = testunit.name + "("
        argdict = CliTestRunner.get_testunit_method_arg_dict(testunit)
        for arg in argdict:
            buf += str(arg) + "=" + str(argdict[arg]) + ", "
        buf = buf.rstrip(',')
        buf += ")"
        return buf

    def getline(self, len):
        buf = ''
        for x in xrange(0, len):
            buf += '-'
        return buf

    def run_method_by_name(self, name, obj=None, *args, **kwargs):
        '''
        Description: Find a method within an instance of obj and run that method with either
        args/kwargs provided or any self.args which match the methods varname.

        :type name: string
        :param name: Name of method to look for within instance of object 'obj'

        :type obj: class instance
        :param obj: Instance type, defaults to self testcase object

        :type args: positional arguements
        :param args: None or more positional arguments to be passed to method to be run

        :type kwargs: keyword arguments
        :param kwargs: None or more keyword arguements to be passed to method to be run
        '''
        obj = obj or self
        meth = getattr(obj, name)
        return self.do_with_args(meth, *args, **kwargs)

    def create_testunit_by_name(self, name, obj=None, eof=True, autoarg=True, *args, **kwargs):
        '''
        Description: Attempts to match a method name contained with object 'obj', and create a
        EutesterTestUnit object from that method and the provided positional as well as keyword
        arguments provided.

        :type name: string
        :param name: Name of method to look for within instance of object 'obj'

        :type obj: class instance
        :param obj: Instance type, defaults to self testcase object

        :type args: positional arguements
        :param args: None or more positional arguments to be passed to method to be run

        :type kwargs: keyword arguments
        :param kwargs: None or more keyword arguements to be passed to method to be run
        '''
        eof = False
        autoarg = True
        obj = obj or self
        meth = getattr(obj, name)
        methvars = self.get_meth_arg_names(meth)

        # Pull out value relative to this method, leave in any that are intended to be
        # passed through
        if 'autoarg' in kwargs:
            if 'autoarg' in methvars:
                autoarg = kwargs['autoarg']
            else:
                autoarg = kwargs.pop('autoarg')
        if 'eof' in kwargs:
            if 'eof' in methvars:
                eof = kwargs['eof']
            else:
                eof = kwargs.pop('eof')
        if 'obj' in kwargs:
            if 'obj' in methvars:
                obj = kwargs['obj']
            else:
                obj = kwargs.pop('obj')

        testunit = TestUnit(meth, *args, **kwargs)
        testunit.eof = eof

        # if autoarg, auto populate testunit arguements from local testcase.args namespace values
        if autoarg:
            self.populate_testunit_with_args(testunit)

        return testunit

    def get_args(self, use_cli=True, file_sections=[], verbose=True):
        '''
        Description: Method will attempt to retrieve all command line arguments presented
        through local testcase's 'argparse' methods, as well as retrieve all EuConfig file
        arguments. All arguments will be combined into a single namespace object held locally
        at 'testcase.args'. Note: cli arg 'config' must be provided for config file valus to be
        store in self.args.

        :type use_cli: boolean
        :param use_cli: Boolean to indicate whether or not to create and read from a cli
                        argparsing object

        :type use_default_file: boolean
        :param use_default_files: Boolean to indicate whether or not to read default config file
                                 at $HOME/.nephoria/nephoria.conf (not indicated by cli)

        :type sections: list
        :param sections: list of EuConfig sections to read configuration values from, and store
                         in self.args.

        :rtype: arparse.namespace obj
        :returns: namespace object with values from cli and config file arguements
        '''
        configfile = None
        args = None
        # build out a namespace object from the config file first
        cf = argparse.Namespace()

        # Setup/define the config file block/sections we intend to read from
        confblocks = file_sections or [self.name, 'global']

        if use_cli:
            # first get command line args to see if there's a config file
            cliargs = self.parser.parse_args()

        # if a config file was passed, combine the config file and command line args into a
        # single namespace object
        if cliargs:
            # Check to see if there's explicit config sections to read
            # if a file or list of config files is specified add it to our list...
            # legacy support for config, configfile config_file arg names...
            config_file = getattr(cliargs, 'config_file', None)
        # store config block list for debug purposes
        cf.__setattr__('configsections', copy.copy(confblocks))

        # create euconfig configparser objects from each file.
        if config_file:
            self.config_file = EuConfig(filename=configfile)
            # Now iterate through remaining config block in file and add to args...
            for section in confblocks:
                if self.config_file.config.has_section(section):
                    for item in self.config_file.config.items(section):
                        cf.__setattr__(str(item[0]), item[1])
        else:
            self.config_file = None

        if cliargs:
            # Now make sure any conflicting args provided on the command line take precedence
            # over config file args
            for val in cliargs._get_kwargs():
                if (val[0] not in cf) or (val[1] is not None):
                    cf.__setattr__(str(val[0]), val[1])
            args = cf
        self.args = args
        return args

    def get_default_userhome_config(self, fname='nephoria.conf'):
        '''
        Description: Attempts to fetch the file 'fname' from the current user's home dir.
        Returns path to the user's home dir default nephoria config file.

        :type fname: string
        :param fname: the nephoria default config file name

        :rtype: string
        :returns: string representing the path to 'fname', the default nephoria conf file.
        '''
        try:
            def_path = os.getenv('HOME') + '/.nephoria/' + str(fname)
        except:
            return None
        try:
            os.stat(def_path)
            return def_path
        except:
            self.log.debug("Default config not found:" + str(def_path))
            return None

    def show_self(self):
        main_pt = PrettyTable([yellow('TEST CASE INFO', bold=True)])
        main_pt.border = False
        pt = PrettyTable(['KEY', 'VALUE'])
        pt.header = False
        pt.align = 'l'
        pt.add_row([blue("NAME"), self.name])
        pt.add_row([blue("TEST LIST"), self._testlist])
        pt.add_row([blue('CONFIG FILES'), self.args.config_file])
        main_pt.add_row([pt])
        self.log.info("\n{0}\n".format(main_pt))
        self.show_args()

    def show_args(self, args=None):
        '''
        Description: Prints args names and values for debug purposes.
                     By default will use the local testcase.args, else args can be provided.

        :type args: namespace object
        :param args: namespace object to be printed,by default None will print local
                     testcase's args.
        '''
        if args is None:
            args = self.args
        if not args:
            return
        pt = PrettyTable([yellow('TEST ARGS', bold=True), yellow('VALUE', bold=True)])
        pt.align = 'l'
        for key, val in args._get_kwargs():
            pt.add_row([blue(key), val])
        self.log.info("\n{0}\n".format(pt))

    def populate_testunit_with_args(self, testunit, namespace=None):
        '''
        Description: Checks a given test unit's available positional and key word args lists
        for matching values contained with the given namespace, by default will use local
        testcase.args. If testunit's underlying method has arguments matching the namespace
        provided, then those args will be applied to the testunits args referenced when running
        the testunit. Namespace values will not be applied/overwrite testunits, if the testunit
        already has conflicting values in it's args(positional) list or kwargs(keyword args) dict.
        :type: testunit: Eutestcase.eutestertestunit object
        :param: testunit: A testunit object for which the namespace values will be applied

        :type: namespace: namespace obj
        :param: namespace: namespace obj containing args/values to be applied to testunit.
                            None by default will use local testunit args.
        '''
        self.log.debug(
            "Attempting to populate testunit:" + str(testunit.name) + ", with testcase.args...")
        args_to_apply = namespace or self.args
        if not args_to_apply:
            return
        testunit_obj_args = {}

        # copy the test units key word args
        testunit_obj_args.update(copy.copy(testunit.kwargs))
        self.log.debug("Testunit keyword args:" + str(testunit_obj_args))

        # Get all the var names of the underlying method the testunit is wrapping
        method_args = self.get_meth_arg_names(testunit.method)
        offset = 0 if isinstance(testunit.method, types.FunctionType) else 1
        self.log.debug("Got method args:" + str(method_args))

        # Add the var names of the positional args provided in testunit.args to check against later
        # Append to the known keyword arg list
        for x, arg in enumerate(testunit.args):
            testunit_obj_args[method_args[x + offset]] = arg

        self.log.debug("test unit total args:" + str(testunit_obj_args))
        # populate any global args which do not conflict with args already contained within the
        # test case first populate matching method args with our global testcase args taking
        # least precedence
        for apply_val in args_to_apply._get_kwargs():
            for methvar in method_args:
                if methvar == apply_val[0]:
                    self.log.debug("Found matching arg for:" + str(methvar))
                    # Don't overwrite existing testunit args/kwargs that have already been assigned
                    if apply_val[0] in testunit_obj_args:
                        self.log.debug("Skipping populate because testunit already has this arg:" +
                                   str(methvar))
                        continue
                    # Append cmdargs list to testunits kwargs
                    testunit.set_kwarg(methvar, apply_val[1])

    def do_with_args(self, meth, *args, **kwargs):
        '''
        Description: Convenience method used to wrap the provided instance_method, function, or
        object type 'meth' and populate meth's positional and keyword arguments with the local
        testcase.args created from the CLI and/or config file, as well as the *args and **kwargs
        variable length arguments passed into this method.

        :type meth: method
        :param meth: A method or class initiator to wrapped/populated with this testcase objects
                     namespace args

        :type args: positional arguments
        :param args: None or more values representing positional arguments to be passed to 'meth'
                     when executed. These will take precedence over local testcase obj
                     namespace args

        :type kwargs: keyword arguments
        :param kwargs: None or more values reprsenting keyword arguments to be passed to 'meth'
                      when executed. These will take precedence over local testcase obj namespace
                      args and positional args
        '''
        if not hasattr(self, 'args'):
            raise Exception(
                'TestCase object does not have args yet, see: get_args and setup_parser options')
        tc_args = self.args
        cmdargs = {}
        f_code = self.get_method_fcode(meth)
        vars = self.get_meth_arg_names(meth)
        self.log.debug("do_with_args: Method:" + str(f_code.co_name) + ", Vars:" + str(vars))

        # first populate matching method args with our global testcase args...
        for val in tc_args._get_kwargs():
            for var in vars:
                if var == val[0]:
                    cmdargs[var] = val[1]
        # Then overwrite/populate with any given positional local args...
        for count, arg in enumerate(args):
            cmdargs[vars[count + 1]] = arg
        # Finall overwrite/populate with any given key word local args...
        for name, value in kwargs.items():
            for var in vars:
                if var == name:
                    cmdargs[var] = value
        self.log.debug(
            'create_with_args: running ' + str(f_code.co_name) + "(" +
            str(cmdargs).replace(':', '=') + ")")
        return meth(**cmdargs)

    @classmethod
    def get_method_fcode(cls, meth):
        f_code = None
        # Find the args for the method passed in...
        # Check for object/class init...
        if isinstance(meth, types.ObjectType):
            try:
                f_code = meth.__init__.__func__.func_code
            except:
                pass
                # Check for instance method...
        if isinstance(meth, types.MethodType):
            try:
                f_code = meth.im_func.func_code
            except:
                pass
                # Check for function...
        if isinstance(meth, types.FunctionType):
            try:
                f_code = meth.func_code
            except:
                pass
        if not f_code:
            raise Exception(
                "get_method_fcode: Could not find function_code for passed method of type:" +
                str(type(meth)))
        return f_code

    @classmethod
    def get_meth_arg_names(cls, meth):
        '''
        Description: Return varnames within argcount
        :type:meth: method
        :param: meth: method to fetch arg names for

        :rtype: list
        :returns: list of strings representing the varnames within argcount for this method
        '''
        fcode = cls.get_method_fcode(meth)
        varnames = fcode.co_varnames[0:fcode.co_argcount]
        return varnames


class SkipTestException(Exception):
    def __init__(self, value='Skipped Test'):
        self.value = value

    def __str__(self):
        return repr(self.value)

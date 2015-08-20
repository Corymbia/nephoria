#!/usr/bin/python

from nephoria.euca.euca_ops import Eucaops
from nephoria.utils.eutestcase import EutesterTestCase


class CreateUser(EutesterTestCase):
    def __init__(self):
        self.setuptestcase()
        self.setup_parser()
        self.parser.add_argument("--account-number",default=1)
        self.parser.add_argument("--account-prefix",default="test-account-")
        self.parser.add_argument("--group-prefix",default="test-group-")
        self.parser.add_argument("--user-prefix",default="test-user-")
        self.parser.add_argument("--password-prefix",default="mypassword")
        self.parser.add_argument("--user-number",default=1)
        self.get_args()
        # Setup basic nephoria object
        self.tester = Eucaops(config_file=self.args.config, password=self.args.password, credpath=self.args.credpath)

    def clean_method(self):
        self.tester.cleanup_artifacts()

    def create_users(self):
        """
        This is where the test description goes
        """
        allow_all_policy = """{
          "Statement": [
            {
             "Action": "*",
              "Effect": "Allow",
              "Resource": "*"
            }]
            }"""

        for i in xrange(self.args.account_number):
            account_name = self.args.account_prefix + str(i)
            group_name = self.args.group_prefix + str(i)
            password = self.args.password_prefix + str(i)
            self.tester.iam.create_account(account_name)
            self.tester.iam.create_group(group_name, "/", account_name)
            self.tester.iam.attach_policy_group(group_name, "allow-all", allow_all_policy, account_name)
            for k in xrange(self.args.user_number):
                user_name = self.args.user_prefix + str(k)
                self.tester.iam.create_user(user_name, "/", account_name)
                self.tester.iam.add_user_to_group(group_name, user_name, account_name)
                self.tester.iam.create_login_profile(user_name, password, account_name)

if __name__ == "__main__":
    testcase = CreateUser()
    ### Use the list of tests passed from config/command line to determine what subset of tests to run
    ### or use a predefined list
    test_list = testcase.args.tests or ["create_users"]

    ### Convert test suite methods to EutesterUnitTest objects
    unit_list = []
    for test in test_list:
        unit_list.append(testcase.create_testunit_by_name(test))

    ### Run the EutesterUnitTest objects
    result = testcase.run_test_case_list(unit_list, clean_on_exit=True)
    exit(result)



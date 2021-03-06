import csv
import io
import json
import os

import yaml
from httprunner import exceptions, logger, parser, utils

###############################################################################
##   file loader
###############################################################################


def _check_format(file_path, content):
    """ check testcase format if valid
    """
    # TODO: replace with JSON schema validation
    if not content:
        # testcase file content is empty
        err_msg = u"Testcase file content is empty: {}".format(file_path)
        logger.log_error(err_msg)
        raise exceptions.FileFormatError(err_msg)

    elif not isinstance(content, (list, dict)):
        # testcase file content does not match testcase format
        err_msg = u"Testcase file content format invalid: {}".format(file_path)
        logger.log_error(err_msg)
        raise exceptions.FileFormatError(err_msg)


def load_yaml_file(yaml_file):
    """ load yaml file and check file content format
    """
    with io.open(yaml_file, 'r', encoding='utf-8') as stream:
        yaml_content = yaml.load(stream)
        _check_format(yaml_file, yaml_content)
        return yaml_content


def load_json_file(json_file):
    """ load json file and check file content format
    """
    with io.open(json_file, encoding='utf-8') as data_file:
        try:
            json_content = json.load(data_file)
        except exceptions.JSONDecodeError:
            err_msg = u"JSONDecodeError: JSON file format error: {}".format(json_file)
            logger.log_error(err_msg)
            raise exceptions.FileFormatError(err_msg)

        _check_format(json_file, json_content)
        return json_content


def load_csv_file(csv_file):
    """ load csv file and check file content format
    @param
        csv_file: csv file path
        e.g. csv file content:
            username,password
            test1,111111
            test2,222222
            test3,333333
    @return
        list of parameter, each parameter is in dict format
        e.g.
        [
            {'username': 'test1', 'password': '111111'},
            {'username': 'test2', 'password': '222222'},
            {'username': 'test3', 'password': '333333'}
        ]
    """
    csv_content_list = []

    with io.open(csv_file, encoding='utf-8') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            csv_content_list.append(row)

    return csv_content_list


def load_file(file_path):
    if not os.path.isfile(file_path):
        raise exceptions.FileNotFound("{} does not exist.".format(file_path))

    file_suffix = os.path.splitext(file_path)[1].lower()
    if file_suffix == '.json':
        return load_json_file(file_path)
    elif file_suffix in ['.yaml', '.yml']:
        return load_yaml_file(file_path)
    elif file_suffix == ".csv":
        return load_csv_file(file_path)
    else:
        # '' or other suffix
        err_msg = u"Unsupported file format: {}".format(file_path)
        logger.log_warning(err_msg)
        return []


def load_folder_files(folder_path, recursive=True):
    """ load folder path, return all files in list format.
    @param
        folder_path: specified folder path to load
        recursive: if True, will load files recursively
    """
    if isinstance(folder_path, (list, set)):
        files = []
        for path in set(folder_path):
            files.extend(load_folder_files(path, recursive))

        return files

    if not os.path.exists(folder_path):
        return []

    file_list = []

    for dirpath, dirnames, filenames in os.walk(folder_path):
        filenames_list = []

        for filename in filenames:
            if not filename.endswith(('.yml', '.yaml', '.json')):
                continue

            filenames_list.append(filename)

        for filename in filenames_list:
            file_path = os.path.join(dirpath, filename)
            file_list.append(file_path)

        if not recursive:
            break

    return file_list


def load_dot_env_file(path):
    """ load .env file and set to os.environ
    """
    if not path:
        path = os.path.join(os.getcwd(), ".env")
        if not os.path.isfile(path):
            logger.log_debug(".env file not exist: {}".format(path))
            return
    else:
        if not os.path.isfile(path):
            raise exceptions.FileNotFound("env file not exist: {}".format(path))

    logger.log_info("Loading environment variables from {}".format(path))
    with io.open(path, 'r', encoding='utf-8') as fp:
        for line in fp:
            variable, value = line.split("=")
            variable = variable.strip()
            os.environ[variable] = value.strip()
            logger.log_debug("Loaded variable: {}".format(variable))


###############################################################################
##   suite loader
###############################################################################


overall_def_dict = {
    "api": {},
    "suite": {}
}
testcases_cache_mapping = {}


def load_test_dependencies():
    """ load all api and suite definitions.
        default api folder is "$CWD/tests/api/".
        default suite folder is "$CWD/tests/suite/".
    """
    # TODO: cache api and suite loading
    # load api definitions
    api_def_folder = os.path.join(os.getcwd(), "tests", "api")
    for test_file in load_folder_files(api_def_folder):
        load_api_file(test_file)

    # load suite definitions
    suite_def_folder = os.path.join(os.getcwd(), "tests", "suite")
    for suite_file in load_folder_files(suite_def_folder):
        suite = load_test_file(suite_file)
        if "def" not in suite["config"]:
            raise exceptions.ParamsError("def missed in suite file: {}!".format(suite_file))

        call_func = suite["config"]["def"]
        function_meta = parser.parse_function(call_func)
        suite["function_meta"] = function_meta
        overall_def_dict["suite"][function_meta["func_name"]] = suite


def load_api_file(file_path):
    """ load api definition from file and store in overall_def_dict["api"]
        api file should be in format below:
            [
                {
                    "api": {
                        "def": "api_login",
                        "request": {},
                        "validate": []
                    }
                },
                {
                    "api": {
                        "def": "api_logout",
                        "request": {},
                        "validate": []
                    }
                }
            ]
    """
    api_items = load_file(file_path)
    if not isinstance(api_items, list):
        raise exceptions.FileFormatError("API format error: {}".format(file_path))

    for api_item in api_items:
        if not isinstance(api_item, dict) or len(api_item) != 1:
            raise exceptions.FileFormatError("API format error: {}".format(file_path))

        key, api_dict = api_item.popitem()
        if key != "api" or not isinstance(api_dict, dict) or "def" not in api_dict:
            raise exceptions.FileFormatError("API format error: {}".format(file_path))

        api_def = api_dict.pop("def")
        function_meta = parser.parse_function(api_def)
        func_name = function_meta["func_name"]

        if func_name in overall_def_dict["api"]:
            logger.log_warning("API definition duplicated: {}".format(func_name))

        api_dict["function_meta"] = function_meta
        overall_def_dict["api"][func_name] = api_dict


def load_test_file(file_path):
    """ load testcase file or testsuite file
    @param file_path: absolute valid file path
        file_path should be in format below:
            [
                {
                    "config": {
                        "name": "",
                        "def": "suite_order()",
                        "request": {}
                    }
                },
                {
                    "test": {
                        "name": "add product to cart",
                        "api": "api_add_cart()",
                        "validate": []
                    }
                },
                {
                    "test": {
                        "name": "checkout cart",
                        "request": {},
                        "validate": []
                    }
                }
            ]
    @return testset dict
        {
            "config": {},
            "testcases": [testcase11, testcase12]
        }
    """
    testset = {
        "config": {
            "path": file_path
        },
        "testcases": []     # TODO: rename to tests
    }
    for item in load_file(file_path):
        if not isinstance(item, dict) or len(item) != 1:
            raise exceptions.FileFormatError("Testcase format error: {}".format(file_path))

        key, test_block = item.popitem()
        if not isinstance(test_block, dict):
            raise exceptions.FileFormatError("Testcase format error: {}".format(file_path))

        if key == "config":
            testset["config"].update(test_block)

        elif key == "test":
            if "api" in test_block:
                ref_call = test_block["api"]
                def_block = _get_block_by_name(ref_call, "api")
                utils._override_block(def_block, test_block)
                testset["testcases"].append(test_block)
            elif "suite" in test_block:
                ref_call = test_block["suite"]
                block = _get_block_by_name(ref_call, "suite")
                testset["testcases"].extend(block["testcases"])
            else:
                testset["testcases"].append(test_block)

        else:
            logger.log_warning(
                "unexpected block key: {}. block key should only be 'config' or 'test'.".format(key)
            )

    return testset


def _get_block_by_name(ref_call, ref_type):
    """ get test content by reference name
    @params:
        ref_call: e.g. api_v1_Account_Login_POST($UserName, $Password)
        ref_type: "api" or "suite"
    """
    function_meta = parser.parse_function(ref_call)
    func_name = function_meta["func_name"]
    call_args = function_meta["args"]
    block = _get_test_definition(func_name, ref_type)
    def_args = block.get("function_meta").get("args", [])

    if len(call_args) != len(def_args):
        raise exceptions.ParamsError("call args mismatch defined args!")

    args_mapping = {}
    for index, item in enumerate(def_args):
        if call_args[index] == item:
            continue

        args_mapping[item] = call_args[index]

    if args_mapping:
        block = utils.substitute_variables_with_mapping(block, args_mapping)

    return block


def _get_test_definition(name, ref_type):
    """ get expected api or suite.
    @params:
        name: api or suite name
        ref_type: "api" or "suite"
    @return
        expected api info if found, otherwise raise ApiNotFound exception
    """
    block = overall_def_dict.get(ref_type, {}).get(name)

    if not block:
        err_msg = "{} not found!".format(name)
        if ref_type == "api":
            raise exceptions.ApiNotFound(err_msg)
        else:
            # ref_type == "suite":
            raise exceptions.SuiteNotFound(err_msg)

    return block


def load_testcases(path):
    """ load testcases from file path
    @param path: path could be in several type
        - absolute/relative file path
        - absolute/relative folder path
        - list/set container with file(s) and/or folder(s)
    @return testcases list, each testcase is corresponding to a file
        [
            testcase_dict_1,
            testcase_dict_2
        ]
    """
    if isinstance(path, (list, set)):
        testcases_list = []

        for file_path in set(path):
            testcases = load_testcases(file_path)
            if not testcases:
                continue
            testcases_list.extend(testcases)

        return testcases_list

    if not os.path.isabs(path):
        path = os.path.join(os.getcwd(), path)

    if path in testcases_cache_mapping:
        return testcases_cache_mapping[path]

    if os.path.isdir(path):
        files_list = load_folder_files(path)
        testcases_list = load_testcases(files_list)

    elif os.path.isfile(path):
        try:
            testcase = load_test_file(path)
            if testcase["testcases"]:
                testcases_list = [testcase]
            else:
                testcases_list = []
        except exceptions.FileFormatError:
            testcases_list = []

    else:
        err_msg = "file not found: {}".format(path)
        logger.log_error(err_msg)
        raise exceptions.FileNotFound(err_msg)

    testcases_cache_mapping[path] = testcases_list
    return testcases_list

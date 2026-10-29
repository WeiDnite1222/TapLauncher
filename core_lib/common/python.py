import ast


def is_function_in_file(file_path, function_name) -> tuple[bool, bool]:
    """
    Parse a Python file via ast module to check if a function exists.
    :param file_path:
    :param function_name:
    :return:
        is_check_success: bool
        is_function_exist: bool
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            root = ast.parse(f.read(), filename=file_path)

        for node in ast.iter_child_nodes(root):
            if isinstance(node, ast.FunctionDef) and node.name == function_name:
                return True, True
        return True, False
    except (FileNotFoundError, SyntaxError):
        return False, False

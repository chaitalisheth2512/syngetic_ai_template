import subprocess
import tempfile
import os
import traceback
from workflow.workflow_datatypes import NodeConfig, FieldType

from jinja2 import Template, TemplateSyntaxError
import json
import time
import re
import subprocess, time


class code_runner_node:
    default_setup: NodeConfig = {
        "id": "CodeRunner",
        "name": "Code Runner",
        "description": "Execute user-provided code in Python, Node.js, C, or Java.",
        "pins": {
            "trigger_pins": [{"name": "Start"}],
            "input_pins": [],
            "output_pins": [{"name": "Response"}],
            "next_pins": [{"name": "Next"}],
        },
        "fields": [
            {
                "id": "language",
                "label": "Language",
                "type": FieldType.SINGLE_SELECT,
                "options": ["Python", "Node.js", "C", "Java"],
            },
            {"id": "code", "label": "Code", "type": FieldType.TEXT},
            # ⭐ NEW FIELD: Python Dependencies
            {
                "id": "dependencies",
                "label": "Dependencies / Packages (one per line)",
                "type": FieldType.TEXT,
            },
            # {
            #     "id": "nodejs_packages",
            #     "label": "Node.js Packages (one per line)",
            #     "type": FieldType.TEXT,
            # },
            {"id": "timeout", "label": "Timeout (sec)", "type": FieldType.NUMBER},
        ],
    }

    def __init__(self, node):
        self.node = node

    def Run(self, connection, data):
        config = self.node.data.get("configuration", {})
        language = config.get("language", "Python")
        code = config.get("code", "")
        print(code,"code---------------")
        timeout_raw = config.get("timeout", 150)
        deps_raw = config.get("dependencies", "")
        # Safe int conversion
        try:
            timeout = int(timeout_raw) if str(timeout_raw).strip() != "" else 150
        except Exception:
            timeout = 150
        response_data = {}

        if isinstance(code, str) and re.search(r"{{.*?}}", code):
            try:
                template = Template(code)
                rendered = template.render(**data)
                code = rendered
            except TemplateSyntaxError as e:
                response_data["error"] = f"Template syntax error: {str(e)}"
                self.node.SetTargetPinData("Response", response_data)
                return self.node.Trigger(["Next"])
        if isinstance(deps_raw, str) and re.search(r"{{.*?}}", deps_raw):
            try:
                template = Template(deps_raw)
                rendered = template.render(**data)
                deps_raw = rendered
            except TemplateSyntaxError as e:
                response_data["error"] = f"Template syntax error: {str(e)}"
                self.node.SetTargetPinData("Response", response_data)
                return self.node.Trigger(["Next"])
        if isinstance(timeout_raw, str) and re.search(r"{{.*?}}", timeout_raw):
            try:
                template = Template(timeout_raw)
                rendered = template.render(**data)
                timeout_raw = rendered
            except TemplateSyntaxError as e:
                response_data["error"] = f"Template syntax error: {str(e)}"
                self.node.SetTargetPinData("Response", response_data)
                return self.node.Trigger(["Next"])
        # print(code,"code---------------")
        # print(deps_raw,"deps_raw---------------")
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                # ------------------------------
                # ⭐ Python Execution Path
                # ------------------------------
                if language == "Python":
                    script_path = os.path.join(temp_dir, "script.py")
                    with open(script_path, "w", encoding="utf-8") as f:
                        f.write(code)
                    # Install Python dependencies (if any)
                    deps = [d.strip() for d in deps_raw.split("\n") if d.strip()]
                    if deps:
                        try:
                            install_cmd = ["pip", "install", "-t", temp_dir] + deps
                            returncode, stdout, stderr = dependency_installation(install_cmd, temp_dir)
                            # print(stdout,"stdout----------------")
                            # print(stderr,"stderr----------------")
                            if returncode != 0:
                                raise Exception(
                                    "Dependency Installation Error:\n"
                                    + stdout
                                    + stderr
                                )
                        except Exception as e:
                            response_data["error"] = f"Dependency Install Error: {str(e)}"
                            response_data["traceback"] = traceback.format_exc()
                            self.node.SetTargetPinData("Response", response_data)
                            return self.node.Trigger(["Next"])
                    # Create isolated Python environment
                    env = os.environ.copy()
                    env["PYTHONPATH"] = temp_dir
                    cmd = ["python", script_path]
                # ------------------------------
                # Node.js Execution
                # ------------------------------
                elif language == "Node.js":
                    script_path = os.path.join(temp_dir, "script.js")
                    with open(script_path, "w", encoding="utf-8") as f:
                        f.write(code)
                    
                    print(code,"code---------------")

                    deps = [d.strip() for d in deps_raw.replace("\n", " ").split(" ") if d.strip()]
                    if deps:
                        try:
                            install_cmd = ["npm.cmd", "init", "-y"]
                            returncode, stdout, stderr = dependency_installation(install_cmd, temp_dir)
                            if returncode != 0:
                                raise Exception(
                                    "package Installation Error:\n"
                                    + stdout
                                    + stderr
                                )
                            install_cmd = ["npm.cmd", "install"] + deps
                            returncode, stdout, stderr = dependency_installation(install_cmd, temp_dir)
                            if returncode != 0:
                                raise Exception(
                                    "Dependency Installation Error:\n"
                                    + stdout
                                    + stderr
                                )
                        except Exception as e:
                            response_data["error"] = f"Dependency Install Error: {str(e)}"
                            response_data["traceback"] = traceback.format_exc()
                            self.node.SetTargetPinData("Response", response_data)
                            return self.node.Trigger(["Next"])

                    cmd = ["node", script_path]
                    env = None
                # ------------------------------
                # C Execution
                # ------------------------------
                # elif language == "C":
                #     print("Running C code using Judge0 Cloud API")

                #     # Judge0 API endpoint (free server)
                #     JUDGE0_URL = "https://ce.judge0.com/submissions/?base64_encoded=false&wait=false"

                #     payload = {
                #         "language_id": 50,   # 50 = GCC C (latest)
                #         "source_code": code,
                #         "stdin": ""
                #     }

                #     headers = {"Content-Type": "application/json"}

                #     # Step 1: Create submission
                #     res = requests.post(JUDGE0_URL, json=payload, headers=headers)
                #     token = res.json()["token"]

                #     # Step 2: Poll result until execution finishes
                #     while True:
                #         result = requests.get(f"https://ce.judge0.com/submissions/{token}?base64_encoded=false")
                #         result_json = result.json()

                #         status = result_json["status"]["description"]
                #         if status not in ["In Queue", "Processing"]:
                #             break
                #         time.sleep(0.5)

                #     if result_json.get("compile_output"):
                #         response_data["stdout"] = None
                #         response_data["stderr"] = result_json["compile_output"]
                #         response_data["exit_code"] = 1
                #         return response_data

                #     output = (
                #         result_json.get("stdout", "")
                #         or result_json.get("stderr", "")
                #         or result_json.get("message", "")
                #     )

                #     response_data["stdout"] = output.strip()
                #     response_data["stderr"] = ""
                #     response_data["exit_code"] = 0
                #     print(response_data,"response_data----------------")

                #     cmd = None
                #     env = None
                #     self.node.SetTargetPinData("Response", response_data)
                #     # Trigger next node
                #     return self.node.Trigger(["Next"])
                elif language == "C":
                    # print("-------------------")
                    c_path = os.path.join(temp_dir, "program.c")
                    exe_path = os.path.join(temp_dir, "program.exe")
                    with open(c_path, "w", encoding="utf-8") as f:
                        f.write(code)
                    gcc_path = r"C:\Tools\mingw64\bin\gcc.exe"
                    # FIX: Add MinGW bin directory to PATH for subprocess
                    env = os.environ.copy()
                    env["PATH"] = r"C:\Tools\mingw64\bin;" + env["PATH"]
                    compile_result = subprocess.run(
                        [gcc_path, c_path, "-o", exe_path],
                        capture_output=True,
                        text=True,
                        env=env
                    )
                    # print(compile_result,"compile_result-------------------")
                    if compile_result.returncode != 0:
                        raise Exception(
                            f"C Compilation Error:\n{compile_result.stderr}"
                        )
                    cmd = [exe_path]
                    env = None

                    # install_cmd=["gcc", c_path, "-o", exe_path]
                    # install_cmd= [r"C:\mingw64\bin\gcc.exe", c_path, "-o", exe_path]
                    # returncode, stdout, stderr = dependency_installation(install_cmd,temp_dir)
                    # print(stdout,"stdout----------------")
                    # print(stderr,"stderr----------------")
                    # if returncode != 0:
                    #     raise Exception(
                    #         f"C Compilation Error:\n{stderr}"
                    #     )
                # ------------------------------
                # Java Execution
                # ------------------------------
                elif language == "Java":
                    java_file = os.path.join(temp_dir, "Main.java")
                    with open(java_file, "w", encoding="utf-8") as f:
                        f.write(code)
                    compile_result = subprocess.run(
                        ["javac", java_file],
                        capture_output=True,
                        text=True,
                    )
                    if compile_result.returncode != 0:
                        raise Exception(
                            f"Java Compilation Error:\n{compile_result.stderr}"
                        )
                    cmd = ["java", "-cp", temp_dir, "Main"]
                    env = None
                else:
                    raise Exception(f"Unsupported language: {language}")
                # ------------------------------
                # Execute Final Command
                # ------------------------------


                print("ready to run code......")
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                print(result,"result of code......")
                stdout = result.stdout.strip()
                stderr = result.stderr.strip()

                # Try to parse JSON cleanly
                clean_stdout = stdout
                try:
                    # Extract only JSON if mixed with logs
                    json_match = re.search(r"{.*}", stdout, re.DOTALL)
                    if json_match:
                        clean_stdout = json.loads(json_match.group(0))
                    else:
                        # Try to parse directly
                        clean_stdout = json.loads(stdout)
                except Exception:
                    # If not JSON, keep plain text
                    clean_stdout = stdout

                response_data["stdout"] = clean_stdout
                response_data["stderr"] = stderr
                response_data["exit_code"] = result.returncode

                # response_data["stdout"] = result.stdout
                # response_data["stderr"] = result.stderr
                # response_data["exit_code"] = result.returncode
        except subprocess.TimeoutExpired:
            response_data["error"] = (
                f"Execution timed out after {timeout} seconds."
            )
        except Exception as e:
            # print(traceback.format_exc(),"eeeeeeeee------------------")
            response_data["error"] = str(e)
            response_data["traceback"] = traceback.format_exc()

        print(response_data,"response_data---------------------")
        # Set response
        self.node.SetTargetPinData("Response", response_data)
        # Trigger next node
        return self.node.Trigger(["Next"])


def dependency_installation(cmd, cwd=None, inactivity_limit=30):
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False  # IMPORTANT: read as bytes, not text!
    )

    last_output_time = time.time()
    stdout_bytes = b""
    stderr_bytes = b""

    while True:
        out = process.stdout.readline()
        err = process.stderr.readline()

        if out:
            stdout_bytes += out
            last_output_time = time.time()

        if err:
            stderr_bytes += err
            last_output_time = time.time()

        # Check if process finished
        if process.poll() is not None:
            break

        # Timeout if no output
        if time.time() - last_output_time > inactivity_limit:
            process.kill()
            raise Exception(f"Installation hung (no output for {inactivity_limit} seconds)")

    # Decode safely
    stdout = stdout_bytes.decode("utf-8", errors="ignore")
    stderr = stderr_bytes.decode("utf-8", errors="ignore")

    return process.returncode, stdout, stderr

# def dependency_installation(cmd, cwd=None, inactivity_limit=30):
#     process = subprocess.Popen(
#         cmd,
#         cwd=cwd,
#         stdout=subprocess.PIPE,
#         stderr=subprocess.PIPE,
#         text=True
#     )

#     last_output_time = time.time()
#     stdout = ""
#     stderr = ""

#     while True:
#         out = process.stdout.readline()
#         err = process.stderr.readline()

#         if out:
#             stdout += out
#             last_output_time = time.time()

#         if err:
#             stderr += err
#             last_output_time = time.time()

#         # Process finished?
#         if process.poll() is not None:
#             break

#         # No output for too long → timeout
#         if time.time() - last_output_time > inactivity_limit:
#             process.kill()
#             raise Exception(
#                 f"Installation hung (no output for {inactivity_limit} seconds)"
#             )

#     returncode = process.returncode
#     return returncode, stdout, stderr


# import subprocess
# import tempfile
# import os
# import traceback
# from workflow.workflow_datatypes import NodeConfig, FieldType

# import subprocess, time

# class code_runner_node:
#     default_setup: NodeConfig = {
#         "id": "CodeRunner",
#         "name": "Code Runner",
#         "description": "Execute user-provided code in Python, Node.js, C, or Java.",
#         "pins": {
#             "trigger_pins": [{"name": "Start"}],
#             "input_pins": [],
#             "output_pins": [{"name": "Response"}],
#             "next_pins": [{"name": "Next"}],
#         },
#         "fields": [
#             {
#                 "id": "language",
#                 "label": "Language",
#                 "type": FieldType.SINGLE_SELECT,
#                 "options": ["Python", "Node.js", "C", "Java"],
#             },
#             {"id": "code", "label": "Code", "type": FieldType.TEXT},
#             # ⭐ NEW FIELD: Python Dependencies
#             {
#                 "id": "python_dependencies",
#                 "label": "Python Dependencies (one per line)",
#                 "type": FieldType.TEXT,
#             },
#             {
#                 "id": "nodejs_dependencies",
#                 "label": "Node.js Dependencies (one per line)",
#                 "type": FieldType.TEXT,
#             },
#             {"id": "timeout", "label": "Timeout (sec)", "type": FieldType.NUMBER},
#         ],
#     }
#     def __init__(self, node):
#         self.node = node
#     def Run(self, connection, data):
#         # print(self.node,"===============")
#         # config = self.node.data.get("configuration", {})
#         config = self.node.get("configuration", {})
#         # print(config,"config===============")
#         language = config.get("language", "Python")
#         code = config.get("code", "")
#         timeout_raw = config.get("timeout", 15)
#         # print(code,"code---------")
#         # print(language,"language---------")
#         # Safe int conversion
#         try:
#             timeout = int(timeout_raw) if str(timeout_raw).strip() != "" else 15
#         except Exception:
#             timeout = 15
#         response_data = {}
#         try:
#             with tempfile.TemporaryDirectory() as temp_dir:
#                 # ------------------------------
#                 # ⭐ Python Execution Path
#                 # ------------------------------
#                 if language == "Python":
#                     script_path = os.path.join(temp_dir, "script.py")
#                     with open(script_path, "w", encoding="utf-8") as f:
#                         f.write(code)
#                     # Install Python dependencies (if any)
#                     deps_raw = config.get("python_dependencies", "")
#                     print(deps_raw,"deps_raw---------")
#                     deps = [d.strip() for d in deps_raw.split("\n") if d.strip()]
#                     if deps:
#                         print("-=-==-=-=-=-=-=-=-=-")
#                         try:
#                             # install_cmd = ["pip", "install", "-t", temp_dir] + deps
#                             # install_result = subprocess.run(
#                             #     install_cmd,
#                             #     capture_output=True,
#                             #     text=True,
#                             #     timeout=60,
#                             # )
#                             # if install_result.returncode != 0:
#                             #     raise Exception(
#                             #         "Dependency Installation Error:\n"
#                             #         + install_result.stdout
#                             #         + install_result.stderr
#                             #     )
#                             install_cmd = ["pip", "install", "-t", temp_dir] + deps
#                             returncode, stdout, stderr = dependency_installation(install_cmd,temp_dir)
#                             print(returncode, stdout, stderr,"+++++++++++++++++++++++")
#                             if returncode != 0:
#                                 raise Exception(
#                                     "Dependency Installation Error:\n"
#                                     + stdout
#                                     + stderr
#                                 )
#                         except Exception as e:
#                             response_data["error"] = f"Dependency Install Error: {str(e)}"
#                             response_data["traceback"] = traceback.format_exc()
#                             # self.node.SetTargetPinData("Response", response_data)
#                             # return self.node.Trigger(["Next"])
#                             print(e,"error+++++++++++++++++++++++")
#                             return response_data
#                     # Create isolated Python environment
#                     env = os.environ.copy()
#                     env["PYTHONPATH"] = temp_dir
#                     cmd = ["python", script_path]
#                 # ------------------------------
#                 # Node.js Execution
#                 # ------------------------------
#                 elif language == "Node.js":
#                     script_path = os.path.join(temp_dir, "script.js")
#                     with open(script_path, "w", encoding="utf-8") as f:
#                         f.write(code)

#                     deps_raw = config.get("nodejs_dependencies", "")
#                     print(deps_raw,"deps_raw------------------")
#                     deps = [d.strip() for d in deps_raw.replace("\n", " ").split(" ") if d.strip()]
#                     if deps:
#                         try:
#                             install_cmd = ["npm.cmd","init", "-y"]
#                             # install_result = subprocess.run(
#                             #     install_cmd,
#                             #     capture_output=True,
#                             #     text=True,
#                             #     timeout=60,
#                             # )
#                             returncode, stdout, stderr = dependency_installation(install_cmd,temp_dir)
#                             if returncode != 0:
#                                 raise Exception(
#                                     "package Installation Error:\n"
#                                     + stdout
#                                     + stderr
#                                 )
#                             install_cmd = ["npm.cmd", "install"] + deps
#                             # install_result = subprocess.run(
#                             #     install_cmd,
#                             #     capture_output=True,
#                             #     text=True,
#                             #     timeout=60,
#                             # )
#                             returncode, stdout, stderr = dependency_installation(install_cmd,temp_dir)
#                             print(returncode, stdout, stderr,"+++++++++++++++++++++++")
#                             if returncode != 0:
#                                 raise Exception(
#                                     "Dependency Installation Error:\n"
#                                     + stdout
#                                     + stderr
#                                 )
#                         except Exception as e:
#                             response_data["error"] = f"Dependency Install Error: {str(e)}"
#                             response_data["traceback"] = traceback.format_exc()
#                             print(e,"error+++++++++++++++++++++++")
#                             return response_data

#                     cmd = ["node", script_path]
#                     env = None
#                     cwd = temp_dir
#                 # ------------------------------
#                 # C Execution
#                 # ------------------------------
#                 elif language == "C":
#                     c_path = os.path.join(temp_dir, "program.c")
#                     exe_path = os.path.join(temp_dir, "program.exe")
#                     with open(c_path, "w", encoding="utf-8") as f:
#                         f.write(code)
#                     compile_result = subprocess.run(
#                         ["gcc", c_path, "-o", exe_path],
#                         capture_output=True,
#                         text=True,
#                     )
#                     if compile_result.returncode != 0:
#                         raise Exception(
#                             f"C Compilation Error:\n{compile_result.stderr}"
#                         )
#                     cmd = [exe_path]
#                     env = None
#                 # ------------------------------
#                 # Java Execution
#                 # ------------------------------
#                 elif language == "Java":
#                     java_file = os.path.join(temp_dir, "Main.java")
#                     with open(java_file, "w", encoding="utf-8") as f:
#                         f.write(code)
#                     compile_result = subprocess.run(
#                         ["javac", java_file],
#                         capture_output=True,
#                         text=True,
#                     )
#                     if compile_result.returncode != 0:
#                         raise Exception(
#                             f"Java Compilation Error:\n{compile_result.stderr}"
#                         )
#                     cmd = ["java", "-cp", temp_dir, "Main"]
#                     env = None
#                 else:
#                     raise Exception(f"Unsupported language: {language}")
#                 # ------------------------------
#                 # Execute Final Command
#                 # ------------------------------
#                 result = subprocess.run(
#                     cmd,
#                     capture_output=True,
#                     text=True,
#                     timeout=timeout,
#                     env=env
#                 )
#                 print(result,"result-=-=-=-=-=-=-=-=-=-=-=")
#                 response_data["stdout"] = result.stdout
#                 response_data["stderr"] = result.stderr
#                 response_data["exit_code"] = result.returncode
#         except subprocess.TimeoutExpired:
#             response_data["error"] = (
#                 f"Execution timed out after {timeout} seconds."
#             )
#         except Exception as e:
#             response_data["error"] = str(e)
#             response_data["traceback"] = traceback.format_exc()
#         # Set response

#         print(response_data,"response------------")
#         # self.node.SetTargetPinData("Response", response_data)
#         # Trigger next node
#         # return self.node.Trigger(["Next"])
#         return response_data

# def dependency_installation(cmd, cwd=None, inactivity_limit=30):
#     process = subprocess.Popen(
#         cmd,
#         cwd=cwd,
#         stdout=subprocess.PIPE,
#         stderr=subprocess.PIPE,
#         text=True
#     )

#     last_output_time = time.time()
#     stdout = ""
#     stderr = ""

#     while True:
#         out = process.stdout.readline()
#         err = process.stderr.readline()

#         if out:
#             stdout += out
#             last_output_time = time.time()

#         if err:
#             stderr += err
#             last_output_time = time.time()

#         # Process finished?
#         if process.poll() is not None:
#             break

#         # No output for too long → timeout
#         if time.time() - last_output_time > inactivity_limit:
#             process.kill()
#             raise Exception(
#                 f"Installation hung (no output for {inactivity_limit} seconds)"
#             )

#     returncode = process.returncode
#     return returncode, stdout, stderr

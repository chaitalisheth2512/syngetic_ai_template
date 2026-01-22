from openai import AzureOpenAI
from flask import Flask, request, jsonify, g, Response
from flask_cors import CORS
from semantic_kernel.functions.kernel_function_decorator import kernel_function
from semantic_kernel.kernel import Kernel
from typing import Annotated, Optional, TypedDict, List,  TypeVar, cast, Callable
from azure.cosmos import CosmosClient, PartitionKey
import requests
from datetime import date
from cachetools import TTLCache
from jinja2 import Template, TemplateSyntaxError
from functools import wraps
import os
import re
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()
from services.chat_service import openai_query, openai_query_withworkflows, conversations_get, conversation_add, message_add, conversation_get
from services.user_service import agent_users_get, all_users_get, user_agent_add, user_agent_remove, agents_get
from datetime import datetime, timedelta

import workflow.workflow_service
import sys

from routes.users import users_bp
from routes.agents import agent_bp
from routes.conversations import conversation_bp


if os.getenv("DEBUGPY") == "1":
    import debugpy
    if os.getenv("DEBUGPY") == "1":
        debugpy.listen(("127.0.0.1", 5678))
        if not debugpy.is_client_connected():
            print("Waiting for debugger attach...")
            debugpy.wait_for_client()


today = date.today()

import os
import json
import uuid

app = Flask(__name__)
CORS(app)


cache = TTLCache(maxsize=100,ttl=600)

devPrompt = f"The current date is {today}. This is important because many of the functions you will be asked to do will require providing dates in relation to the current day. You are a financial assistant bot. You have access to powerful financial functions to do various kinds of financial analysis. Many functions will return formatting instructions a long with the response data, it's important that you adhere to the formatting instructions when they are provided. If the user has asked for multiple values, run all the necessary functions to get all the necessary data."


F = TypeVar('F', bound=Callable[..., Response])
def authorized(required_roles=None) -> Callable[[F], F]:
    def decorator(f:F) -> F:
        @wraps(f)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("x-user-id")
            user_roles_raw = request.headers.get("x-user-roles")
            try:
                user_roles = json.loads(user_roles_raw or "[]")
            except:
                user_roles = []

            if not user_id:
                return jsonify({"error": "Unauthorized"}), 401

            if required_roles:
                if not any(role in user_roles for role in required_roles):
                    return jsonify({"error": "Forbidden"}), 403

            # Attach user info to request context if needed
            g.user_id = user_id
            g.user_roles = user_roles
            return f(*args, **kwargs)
        return cast(F, wrapper)
    return decorator



class FinalytixPlugin:


    @kernel_function(name="securities_performance", description="Returns information about the securities level performance for a user. This information is relevant if the user's question pertains to Security, Securities, or Instrument.")
    async def securities_performance(self,
                                      startDate:Annotated[str,"The start date for the time frame the user is asking about. Should be of the form YYYY-MM-DD. If the user hasn't specified, default to the start of the current year."],
                                        endDate:Annotated[str,"The end date for the time frame the user is asking about. Should be of the form YYYY-MM-DD. If the user hasn't specified, default to 3 days before the current date."]):
        body = {
                "sessionId": "00000000-0000-0000-0000-000000000000",
                "type": "Performance:Security",
                "parameters":
                {
                    "startDate": f"{startDate}",
                    "endDate": f"{endDate}"
                }
            }
        
        url = "https://uatexpertapi.finalytix.com"
        response = requests.post(url,json=body)
        responseObj = response.json()
        data = responseObj.get("data").get("cognitionOperationContexts")[0].get("data")
        if len(data)>=50:
            resp_id = uuid.uuid4()
            cache[str(resp_id)] = data
            data = 'The data response was too large. Please respond with a Jinja2 template that you would use to construct the appropriate answer to the question, provided the data was in an array called "data" and was provided in the following format: ' + json.dumps(data[:5]) + '. Your jinja2 template should not have any newline breaks anywhere, use <p></p> or <br> for line breaks if necessary. Your answer should be a JSON blob of the format {id:"' + str(resp_id) + '",jinja2:"<the jinja2 template>"}. You should not include any other text outside of the JSON blob.'
        formatting_instructions = """
Response Formatting:
1. For Two or Fewer Items:
Present the information as a descriptive summary in sentence form.
Example:
"The portfolio managed by [Wealth Manager Name] has an unrealized gain of $12,345.67 and a profit/loss percentage of 4.56%."
2. For Three or More Items:
Provide a summary followed by a structured table.
Example:
"Based on the data provided, the best performance was by [Wealth Manager Name] with a return of 5.78%, while the worst was by [Wealth Manager Name] with -2.34%. Below are the detailed results:"
(Include the table with a row for every entry in the JSON array)
Table Formatting Guidelines:

When structuring the table, ensure no rows are omitted from the API response. Use the following columns if the corresponding data is available:

Asset Class: Corresponds to assetClassName. Include only if there is more than one Asset Class.
Portfolio Code: Corresponds to portfolioCode. Include only if there is more than one Portfolio Code.
Wealth Manager Name: Corresponds to wealthManagerName.
Instrument Name: Corresponds to instrumentName.
Return (%): Corresponds to irr. Append % to the value.
Profit or Loss (%): Corresponds to profitOrLoss. Append % to the value.
Amount Invested: Corresponds to amountInvested. Prefix with $ and format with commas.
Unrealized Gain: Corresponds to unRealziedGainLoss. Prefix with $.
Realized Gain/Loss: Corresponds to realizedGainLoss. Prefix with $.
Interest/Dividends: Corresponds to intOrDiv. Prefix with $.
Opening Value: Corresponds to openingBalance. Prefix with $.
Closing Value: Corresponds to closingBalance. Prefix with $.
Formatting Rules:
Numerical Values: Format to two decimal places.
Percentages: Append % to all percentage values.
Dollar Amounts: Prefix with $ and use commas to format thousands (e.g., $1,234.56).
Ordering Rows:
If assetClassVar contains a specific order (not just "all"), arrange rows to match this order.
If no specific order is provided or assetClassVar equals "all," retain the order from the API response.
Completeness: Ensure all rows in the API response are included in the table.


Example:
Descriptive (two or fewer items):

"The portfolio managed by [Wealth Manager Name] has an unrealized gain of $12,345.67 and a profit/loss percentage of 4.56%."

Tabular (three or more items):

"Based on the data provided, for the time period {{startDate}} through {{endDate}}, the best performance was by [Instrument Name] in portfolio [Portfolio Code] with a return of 5.78%, while the worst was by [Instrument Name] in portfolio [Portfolio Code] with -2.34%. Below are the detailed results:"
<div style='max-height:600px;overflow-y:auto'>
<table border="1">
  <thead>
    <tr>
      <th>Asset Class</th>
      <th>Portfolio Code</th>
      <th>Wealth Manager Name</th>
      <th>Instrument Name</th>
      <th>Return (%)</th>
      <th>Profit or Loss (%)</th>
      <th>Amount Invested</th>
      <th>Unrealized Gain</th>
      <th>Realized Gain/Loss</th>
      <th>Interest/Dividends</th>
      <th>Opening Value</th>
      <th>Closing Value</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Equity</td>
      <td>ABC123</td>
      <td>John Doe</td>
      <td>Stock A</td>
      <td>5.78%</td>
      <td>3.45%</td>
      <td>$12,345.67</td>
      <td>$1,234.56</td>
      <td>$123.45</td>
      <td>$45.67</td>
      <td>$10,000.00</td>
      <td>$13,579.68</td>
    </tr>
    <tr>
      <td>Fixed Income</td>
      <td>DEF456</td>
      <td>Jane Smith</td>
      <td>Bond B</td>
      <td>-2.34%</td>
      <td>-1.12%</td>
      <td>$15,678.90</td>
      <td>-$456.78</td>
      <td>-$89.12</td>
      <td>$56.78</td>
      <td>$16,000.00</td>
      <td>$15,121.12</td>
    </tr>
  </tbody>
</table>
</div>

By adhering to these guidelines, ensure all user queries are addressed efficiently, professionally, and without omission of data.

Table Formatting Rules:

Include borders for all rows and columns (border="1").
Use bold headers (<th><b></b></th>) with center alignment (style="text-align:center;").
Align string values to the left (style="text-align:left;") and numeric values to the right (style="text-align:right;").
By adhering to these instructions, ensure responses are presented in a concise, structured, and visually clear HTML format, focusing on relevance and accuracy.

Unless otherwise specified, please order the table by the Return (%) field in descending order.
"""
        return {
            "formatting_instructions" : formatting_instructions,
            "results" : data}

    @kernel_function(name="asset_performance", description="Returns information about the performance of the current user's portfolio at an asset level. This information is relevant if the user's question pertains to 'Asset' or 'Asset Level'")
    async def asset_performance(self,
                                      startDate:Annotated[str,"The start date for the time frame the user is asking about. Should be of the form YYYY-MM-DD. If the user hasn't specified, default to the start of the current year."],
                                        endDate:Annotated[str,"The end date for the time frame the user is asking about. Should be of the form YYYY-MM-DD. If the user hasn't specified, default to 3 days before the current date."]):
        body = {
                "sessionId": "00000000-0000-0000-0000-000000000000",
                "type": "Performance:Asset",
                "parameters":
                {
                    "startDate": f"{startDate}",
                    "endDate": f"{endDate}"
                }
            }
        
        url = "https://uatexpertapi.finalytix.com"
        response = requests.post(url,json=body)
        formatting_instructions = f"""

If providing information for more than two values, structure the response as a table.
If there are two or fewer values, present the response in a descriptive sentence format.
Table Response Guidelines:

Begin with a single-sentence summary including:
The best and worst performance based on the "Return (%)" or "Profit or Loss (%)" values.
Any relevant dates or parameters from the input.
Use the following table columns only, extracting them from the API response:

Asset Class: Corresponds to the assetClassName in the API response.
Portfolio Code: Corresponds to portfolioCode in the API response.
Wealth Manager Name: Corresponds to wealthManagerName.
Return (%): Corresponds to irr. Append a percent symbol to the value.
Profit or Loss ($): Corresponds to profitOrLoss. Prefix values with $.
Amount Invested: Corresponds to amountInvested. Prefix values with $ and format with commas for thousands.
Unrealized Gain: Corresponds to unRealizedGain. Prefix values with $.
Realized Gain/Loss: Corresponds to realizedGainLoss. Prefix values with $.
Interest/Dividends: Corresponds to intOrDiv. Prefix values with $.
Opening Value: Corresponds to openingBalance. Prefix values with $.
Closing Value: Corresponds to closingBalance. Prefix values with $. 

Al Start: Corresponds to alStart. Include the value as-is.

Al End: Corresponds to alEnd. Include the value as-is.

Formatting Rules:
All values should be formatted to two decimal places.
Append % to percentage values and use $ for dollar amounts.
Do not do any filtering of your own unless explicitly requested by the user.

Unless otherwise requested, please sort the data by the Return (%) column in descending order.

If the user has mentioned specific Asset Classes they care about, such as Fixed Income, or Stocks, or Real Estate, then sort by those values.

Example Responses::
"Based on the data provided, the best performance was by Asset Class '[Asset Class]' in portfolio '[Portfolio Code]' with a return of 5.78%, while the worst was by Asset Class '[Asset Class]' in portfolio '[Portfolio Code]' with -2.34%. Below are the detailed results:"
(Follow with the table as structured above.)

By adhering to these guidelines, ensure user queries are addressed efficiently and accurately while maintaining clarity and professionalism.
"""
        return {
            "formatting_instructions" : formatting_instructions,
            "results" : response.json()}

    @kernel_function(name="institution_performance", description="Returns information about the performance of the current user's portfolio at an institutional level. This information is relevant if the user's question pertains to 'Portfolio' or 'Institution'")
    async def institution_performance(self,
                                      startDate:Annotated[str,"The start date for the time frame the user is asking about. Should be of the form YYYY-MM-DD. If the user hasn't specified, default to the start of the current year."],
                                        endDate:Annotated[str,"The end date for the time frame the user is asking about. Should be of the form YYYY-MM-DD. If the user hasn't specified, default to 3 days before the current date."]):
        body = {
                "sessionId": "00000000-0000-0000-0000-000000000000",
                "type": "Performance:Institution",
                "parameters":
                {
                    "startDate": f"{startDate}",
                    "endDate": f"{endDate}"
                }
            }
        
        url = "https://uatexpertapi.finalytix.com"
        response = requests.post(url,json=body)
        formatting_instructions = """
    Return your results in the form of a table. Start with a single sentence summary that includes the best & worst performance based on the return/display values (unless there is only one result in which case just summarize the result). In the summary, also provide other information such as dates and any parameters used to get the input. If the column is measured in percentage, make sure to add a percent sign at the end of each value. If the table column is a dollar value, make sure to return the values in that column preceded by the $ sign and use commas to separate larger values. Constraint any values to only two decimals. If using a table, use only the following information from the first level of data. Do not display portfolio details in the table.

When using a table, the following are the columns that are absolutely required to be shown to the user.

Portfolio Code,
Wealth manager name,
Return (%),
Profit or Loss (%),
Amount Invested,
Unrealized Gain,
Realized Gain/Loss,
Interest/Dividends,
Opening Value,
Closing Value,

Make sure all the items from the table are extracted from the API response. 

Following is the mapping of the elements in API response to the columns of the table

portfolioCode: Portfolio Code
wealthManagerName: Wealth Manager Name
openingBalance: Opening Value
closingBalance: Closing Value
realizedGainLoss: Realized Gain/Loss
intOrDiv: Interest/Dividend
unRealziedGainLoss: Unrealized Gain
profitOrLoss: Profit or Loss (%)
amountInvested: Amount Invested
irr: Return (%)

If the user is asking a question for a subset of items available in the 'API response', provide details only about them. Do not do any math on the numbers.

Make sure your response includes the timeframe used for this request

Unless otherwise specified, please order the table by the Return (%) field in descending order.
"""
        return {
            "formatting_instructions" : formatting_instructions,
            "results" : response.json()}

    @kernel_function(name="beta_volatility_analysis", description="Get Beta or Volatility Analysis Information. Should be invoked when the user is asking for a Beta or Volatility Analysis.")
    async def beta_volatility_analysis(self,
                                 type:Annotated[str,"Beta or Volatility. Can only return one set at a time so if you need both you need to call this function twice. Case is important, must be Beta with a capital B or Volatility with a capital V"],
                                 startDate:Annotated[str,"The start date for the time frame the user is asking about. Should be of the form YYYY-MM-DD. If the user hasn't specified, default to the start of the current year."],
                                        endDate:Annotated[str,"The end date for the time frame the user is asking about. Should be of the form YYYY-MM-DD. If the user hasn't specified, default to 3 days before the current date."],
                                 frequency:Annotated[str,"This parameter is to identify from the user if the returns to be calculated for beta analysis on daily, weekly, or monthly. If the user hasn't said they don't want to use default parameters then this value should be 'weekly'"],
                                 returnScale:Annotated[str,"This parameter is to identify from the user if the returns to be calculated for beta analysis is in a logarithmic or arithmetic scale. If the user hasn't said they don't want to use default parameters then this value should be 'arithmetic'. Otherwise ask them which Scale of Returns to use."],
                                 benchmarkIndex:Annotated[str,"This is the Benchmark that is required for calculating the beta analysis. Some examples of this parameter are S&P, Dow Jones, Nikkei, TSX, Russell, Nifty, etc. If the user hasn't said they don't want to use default parameters then this value should be 'SP500' Otherwise, ask them which benchmark to use."],
                                 symbols:Annotated[List[str],"The ticker symbols for the companies mentioned in the user's query. For example Netflix would be NFLX, Tesla would be TSLA"]
                                 ):
        body = {
                "sessionId": "00000000-0000-0000-0000-000000000000",
                "type": f"{type}",
                "parameters":
                {
                    "startDate": f"{startDate}",
                    "endDate": f"{endDate}",
                    "frequency": f"{frequency}",
                    "returnType": f"{returnScale}",
                    "benchmarkIndex": f"{benchmarkIndex}",
                    "symbols": symbols
                }
            }
        url = "https://uatexpertapi.finalytix.com"
        response = requests.post(url,json=body)
        formatting_instructions = f"""Return the results in table format. The header for the Stock column should be "Company". Before the table, start with a brief summarization of the best and worst values for example "Amazon has the highest beta at 1.89, indicating higher volatility compared to the market, while Apple
has the lowest beta at 0.79, indicating lower volatility compared to the market."

Constraint any values to only 2 decimals. In the response, look at the error flag. If the "error" flag is true, gracefully let the user know that you are unable to find the answer at this time. Create a new way of saying this to the user.

If the user is asking a question for a subset of items available in the 'API response', provide details only about them. Do not do any math on the numbers.

The start of your response, before your summary sentence, you should always begin with "The {type} of [list of stocks requested] was calculated using the following parameters:" followed by a bullet point list of the format:

Start Date: {startDate}
End Date: {endDate}
Scale of Returns: {returnScale}
Frequency: {frequency}
Benchmark: {benchmarkIndex}

If the user has asked for both beta and volatility you can combine the results into a single table with one column for Beta and one column for Volatility
"""
        return {
            "formatting_instructions" : formatting_instructions,
            "results" : response.json()}
   
def get_plugin_functions(function,name):
    kernel=Kernel()
    plugin = kernel.add_plugin(function,name)
    functions = []
    metadata = plugin.get_functions_metadata()
    for function in metadata:
        function_processed = {
            "name":function.name,
            "type":"function",
            "description":function.description
        }
        parameters = { "type":"object", "properties":{},"additionalProperties":False}
        for parameter in function.parameters:
            parameters["properties"][parameter.name] = parameter.schema_data
        function_processed["parameters"] = parameters
        functions.append(function_processed)
    return functions

async def openai_query_withtools(body):
    
    response = await openai_query(body)
    toolUsed = False
    for output in response.output:
        if output.type != "function_call":
            data = is_valid_json_with_key(output.content[0].text,"jinja2")
            if data is not None:
                try:
                    template = Template(data["jinja2"])
                except TemplateSyntaxError as e:
                    body["previous_response_id"] = response.id
                    body["input"].append({
                        "role":"assistant",
                        "content":f"Jinja2 Parsing failed with error: {e}. I need to try again"
                    })
                    print(e)
                    return await openai_query_withtools(body)
            continue
        toolUsed = True
        
        finalytixPlugin = FinalytixPlugin()
        arguments = json.loads(output.arguments)
        function_name = output.name
        method = getattr(finalytixPlugin,function_name)
        result = ""
        print(function_name)
        print(output.arguments)
        try:
            result = await method(**arguments)
        except Exception as exception:
            result = exception        
        body["input"].append({
            "type":"function_call_output",
            "call_id":output.call_id,
            "output": str(result)
        })
    if toolUsed==True:
        body["previous_response_id"] = response.id
        return await openai_query_withtools(body)
    return response


def is_valid_json_with_key(s, key):
    try:
        data = json.loads(s)
        if isinstance(data, dict) and key in data:
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return None

# from mcp.server.fastmcp import FastMCP
# mcp = FastMCP("SyngentixMCP")

# @mcp.resource("syngentix://favoritenumber")
# def get_favoritenumber():
#     return {"number":23}

@app.route('/openai_finalytix',methods=['POST'])
@authorized()
def openai_query_finalytix_route() -> Response:
    body = request.get_json()
   
    body['tools'] = get_plugin_functions(FinalytixPlugin(),"FinalytixPlugin")
    if "previous_response_id" not in body or body["previous_response_id"] == None:
        body["input"].insert(0,{
            "role":"developer",
            "content":devPrompt
        })
    response = openai_query_withtools(body)
    responseText = response.output[0].content[0].text
    data = is_valid_json_with_key(responseText,"jinja2")

    if data is not None:
        template = Template(data["jinja2"])
        responseText = template.render(data=cache.get(data["id"]))
        print(responseText)
    return jsonify({"id":response.id, "text":responseText})

@app.route('/tools',methods=['GET'])
def get_tools():
    return jsonify(get_plugin_functions(FinalytixPlugin(),"FinalytixPlugin"))



@app.route('/tempFinalytixData',methods=['GET'])
def tempFinalytixData():
    start_date = "2025-01-01"
    end_date1 = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    end_date2 = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    external_id = request.headers.get("x-user-external-id")
    yesterday_result = get_temp_data(external_id=external_id, start_date=start_date, end_date=end_date1)
    today_result = get_temp_data(external_id=external_id,start_date=start_date, end_date=end_date2)

    yesterday_formatted = f"${yesterday_result:,}"
    today_formatted = f"${today_result:,}"

    if yesterday_result != 0:
        change = round(((today_result - yesterday_result) / yesterday_result) * 100, 4)
        change_str = f"{change}%"
    else:
        change_str = "N/A"

    return {
        "yesterday": yesterday_formatted,
        "today": today_formatted,
        "change": change_str
    }

def get_temp_data(external_id:str | None, start_date: str, end_date: str, retry_attempt: int = 0) -> int:
    url = "https://uatexpertapi.finalytix.com"
   
    request_body = {
        "type": "Performance:Institution",
        "parameters": {
            "startDate": start_date,
            "endDate": end_date
        },
        "userId": external_id
    }

    try:
        response = requests.post(url, json=request_body)
    except requests.RequestException:
        if retry_attempt < 3:
            return get_temp_data(external_id,start_date, end_date, retry_attempt + 1)
        else:
            raise

    if not response.ok:
        if retry_attempt < 3:
            return get_temp_data(external_id,start_date, end_date, retry_attempt + 1)
        else:
            raise Exception(f"Request failed after {retry_attempt} retries")

    fin_response = response.json()

    # Check for error flags
    error_flag = fin_response.get("error", False)
    contexts = fin_response.get("data", {}).get("cognitionOperationContexts", [])
    context_error = contexts and contexts[0].get("error", False)

    if (error_flag or context_error) and retry_attempt < 3:
        return get_temp_data(external_id,start_date, end_date, retry_attempt + 1)

    # Sum up closing values
    total_value = 0
    for item in contexts[0].get("data", []):
        closing_str = item.get("closingValue", "$0")
        try:
            closing = int(closing_str[1:])  # Remove leading '$'
            total_value += closing
        except ValueError:
            continue

    return total_value



@app.route('/',methods=['GET'])
def welcome():
    return "Hello World!"  




app.register_blueprint(users_bp)
app.register_blueprint(agent_bp)
app.register_blueprint(conversation_bp)

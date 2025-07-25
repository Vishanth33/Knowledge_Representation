from pandas import DataFrame
from sqlalchemy import create_engine, text
from langchain_community.utilities import SQLDatabase
from langchain_community.tools.sql_database.tool import QuerySQLDataBaseTool
from langchain_core.tools import tool
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnablePassthrough
from operator import itemgetter
from langchain_core.output_parsers import StrOutputParser
from langchain.chains.sql_database.query import create_sql_query_chain
import streamlit as st
import src.Tools as Tools 

@st.cache_resource
def get_sqlite_engine():
    """
    Returns a SQLAlchemy engine object for database operations.

    If the engine object is not already stored in the session state, it creates a new engine object,
    loads a CSV file into a DataFrame, sets the DataFrame and its columns as session state,
    creates a SQLite database, drops any existing tables in the database, and inserts the DataFrame
    into a new table named 'db'.

    Returns:
        engine (sqlalchemy.engine.Engine): The SQLAlchemy engine object.
    """
    engine = None
    if st.session_state.engine is None:
        df = Tools.load_csv_files(Tools.PATH, key='dataframe')
        st.session_state.df = df
        print("\n")
        print(df.head())
        print("\n")
        # setting columns as session state
        st.session_state.columns = list(df.columns)
        engine = create_engine("sqlite:///db.db")

        # delete the database if it exists
        connection = engine.connect()
        connection.execute(text('DROP TABLE IF EXISTS db'))
        # drop all tables in the database
        connection.execute(text('DROP TABLE IF EXISTS db'))

        df.to_sql("db", engine, index=False)
        
        st.session_state.engine = engine
    else:
        engine = st.session_state.engine
    return engine

def remove_markdown_code_block(sql_code):
    """
    Removes the Markdown code block formatting from a SQL code string.

    Parameters:
    sql_code (str): The SQL code string to remove Markdown code block formatting from.

    Returns:
    str: The SQL code string without Markdown code block formatting.
    """
    if sql_code.startswith("```sql") and sql_code.endswith("```"):
        return sql_code[6:-3].strip()
    
    print("SQL Code: ", sql_code)
    return sql_code

@tool
def pretty_print_result(user_question:str, result: str = ''):
    """
    Formats the result of a SQL query for display in the chatbot.

    Parameters:
        user_question (str): The original user question.
        result (str, optional): The result of the SQL query. Defaults to an empty string.

    Returns:
        str: The formatted result of the SQL query.
    """
    
    strict_llm = st.session_state.strict_llm
    result = result.strip()
    prompt = PromptTemplate.from_template(
        """You are an expert that can reformate the SQL result to make it more readable for the user.
        Given the following user question and SQL result, reformat the SQL result to make it more readable for the user. If the SQL result is already in a readable format, you can simply copy it as is.
        Ensure that your response directly answers the user's question using the information from the SQL result.

        User Question: {user_question}
        SQL Result: {result}

        Reformatted Answer:

        """
    )
    chain = (
        RunnablePassthrough.assign(user_question=user_question).assign(result=result) | prompt | strict_llm | StrOutputParser()
    )

    return chain.invoke({"user_question": user_question, "result": result})


@tool
def database_tool(query: str):
    """Use this to perform SELECT queries to get information from the database that has a table 'db' containing the user's uploaded data."""    
    db = SQLDatabase(engine=get_sqlite_engine(), include_tables=["db"])
    execute_query = QuerySQLDataBaseTool(db=db,verbose=True,handle_tool_error=True)
    write_query = create_sql_query_chain(st.session_state.strict_llm, db,k=100)
    column_names:list[str] = st.session_state.columns
    column_names = ", ".join(column_names)
    answer_prompt = PromptTemplate.from_template(
        """Given the following user question, corresponding SQL query, and SQL result, answer the user question. Make sure correct column names are used in the SQL query.
        If the SQL result contains relevant information, use it to answer the question directly.
        Do not say you don't have access to the information if the SQL result contains relevant data.

        Question: {question}
        Column Names: {column_names}
        SQL Query: {query}
        SQL Result: {result}
        Answer: """
    )

    chain = (
        RunnablePassthrough.assign(query=write_query|remove_markdown_code_block).assign(
            result=itemgetter("query") | execute_query
        )
        | answer_prompt
        | st.session_state.strict_llm
        | StrOutputParser()
    )
    
    return chain.invoke({"question": query, "column_names": column_names})

@tool
def handle_unexpected_query(query: str):
    """
    Handles unexpected queries or user inputs by providing a generic response.

    Parameters:
        query (str): The unexpected query or user input.

    Returns:
        str: A generic response to the unexpected query or user input.
    """
    return "I'm sorry, I couldn't understand your request. Could you please rephrase or provide more information?"

@tool
def describe_dataset(query: str):
    """
    Use this function to describe the dataset, provide basic statistics, or answer questions about the structure of the data without performing SQL queries.

    Parameters:
        query (str): The query or question about the dataset.

    Returns:
        str: The response to the query or question about the dataset.

    Examples:
        >>> describe_dataset("describe")
        "Here's a statistical description of the numerical columns in the dataset: ..."
        
        >>> describe_dataset("columns")
        "The dataset contains the following columns: ..."
        
        >>> describe_dataset("shape")
        "The dataset has ... rows and ... columns."
        
        >>> describe_dataset("sample")
        "Here's a sample of the first few rows of the dataset: ..."
        
        >>> describe_dataset("unknown")
        "I'm sorry, I couldn't understand your request about the dataset. Could you please be more specific? You can ask about the dataset's description, statistics, columns, shape, or a sample of the data."
    """
    df:DataFrame = st.session_state.df
    print(str)
    if "describe" in query.lower() or "statistics" in query.lower():
        description = df.describe().to_html()
        print(description)
        return f"Here's a statistical description of the numerical columns in the dataset:\n{description}"
    
    elif "columns" in query.lower() or "fields" in query.lower():
        columns = ", ".join(df.columns)
        return f"The dataset contains the following columns: {columns}"
    
    elif "shape" in query.lower() or "size" in query.lower():
        rows, cols = df.shape
        return f"The dataset has {rows} rows and {cols} columns."
    
    elif "sample" in query.lower():
        sample = df.head().to_string()
        return f"Here's a sample of the first few rows of the dataset:\n{sample}"
    
    else:
        return "I'm sorry, I couldn't understand your request about the dataset. Could you please be more specific? You can ask about the dataset's description, statistics, columns, shape, or a sample of the data."

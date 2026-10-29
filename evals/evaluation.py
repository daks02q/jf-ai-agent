from openai.resources.content_provenance_checks import AsyncContentProvenanceChecksWithRawResponse
from ragas import experiment, Dataset
from openai import AsyncOpenAI
from ragas.llm import LLMFactory    
from ragas.metrics.collection import ContextRelevance, FactualCorrectness, ToolUseAccuracy, Faithfulness, FactualCorrectness, ContextPrecision, NoiseSensitivty
from ragas.messages import AIMessage, HumanMessage, ToolMessage, SystemMessage
import asyncio
from db.engine import myconext_session_maker, session_maker
from dotenv import load_dotenv
from graph.graph import graph 
import os 
from pathlib import Path
import pandas as pd
import json
import numpy as np
from graph.graph import graph 
from langchain_openai import OpenAI 
import os
from helpers.schema_context import SCHEMA_CONTEXT
from ragas.llms import InstructorBaseRagasLLM, llm_factory 
from typing import Dict
from pathlib import Path

load_dotenv()


client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
client2 = AsyncOpenAI(api_key = os.getenv("GPT_KEY"))
llm = llm_factory("gpt-4o-mini", client2)


# SCORERS
faith = Faithfulness(llm = llm) 


scorer_categories = { 
    'faith' : Faithfulness(llm),
    'factual_correctneses' : FactualCorrectness(llm),


}

def llm_test_generator(category : str) -> InstructorBaseRagasLLM | None: 
    if category in scorer_categories.keys():
        return scorer_categories.get(category)
    else: 
        return None 
        
compiled = graph.compile()


"""GATHERING DATASET FOR EVALUATION BIT"""

def input_experiment_data(data : str, experiment_run : int, experiment_name : str): 
    """ This function is helping to create a dataset for the evaluation of the model.
    It takes in the data, queues them up for evaluation, and saves them in a CSV file for later use."""

    # load the existing dataset 
    try: 
        existing_dataset = pd.read_csv('evaluation_dataset.csv')
    except FileNotFoundError:
        existing_dataset = pd.DataFrame(columns = ["experiment_run", "experiment_name", "query", "expected_answer", "tool_calls", "tool_outputs", "model_response", "score"])
        pd.to_csv(existing_dataset, 'evaluation_dataset.csv', index = True)
        
    # get the new data
    new_data = pd.DataFrame(data, columns = ['experiment_run', 'experiment_name', 'query', 'expected_answer', 'tool_calls', 'tool_outputs', 'model_response'])

    #append the data to the existing dataset
    updated_dataset = pd.concat([existing_dataset, new_data])

    # save the updated dataset to a CSV file
    updated_dataset.to_csv('evaluation_dataset.csv', index = False)



def test_dataset( category : str, llm  : object): 

    """ this function is to test the dataset created for evaluation. It will use an LLM as a curator to make question based on the context we give it"""
    sys_prompt = "You are a curator for a question dataset. you will make a dataset of question that will be used to evaluate a model. The model's current functions are as follows: \n\n"
    sys_prompt += "1. The model can answer questions based on the context provided to it. \n"
    sys_prompt += "2. The model can call tools to get information from the database \n"
    sys_prompt += "3. The model can also acts as RAG agent to get information from the database and answer questions based on the context provided to it"
    sys_prompt += "4. The model output should in JSON format only, with the following keys: \n"
    sys_prompt += "- question \n"
    sys_prompt += "- context type (this covers the tool call targeted at)\n"
    sys_prompt += "- category \n"
    sys_prompt += f"5. the category to check for is {category}"


    client = OpenAI(model_name = os.getenv("MODEL_NAME"), temperature = 0.0, openai_api_base = os.getenv("OPENAI_API_BASE"), openai_api_key = os.getenv("OPENAI_API_KEY"))
    prompt = "Make a question dataset based on the context provided. The context is as follows: \n\n" + sys_prompt + "\n\n The dataset schema is provided as follows:\n" + SCHEMA_CONTEXT

    dataset = pd.DataFrame(columns = ['questions', 'context_type', 'category'])
    for i in range(10): 
        response = client.generate(prompt)
        data = json.loads(response)
        columns = ['question', 'context_type']
        dataset = dataset.append(pd.DataFrame(data, columns = columns), ignore_index = True)

    pd.to_csv(dataset, 'input_dataset.csv', index = False)
    

@experiment
async def gather_dataset(): 
    """ this function is to run multiple looped experiments to evaluate the model performance.
    This will act as the baseline data for testing
    """

    try:
    #load the dataset
        questions = pd.read_csv("input_dataset.csv")
        data = pd.DataFrame(columns = ["experiment_run", "experiment_name", "query", "expected_answer", "tool_calls", "tool_outputs", "model_response", "category"])
        for index, row in questions.iterrows(): 
            query = row['question']
            context_type = row['context_type']
            category = row['category']
            result = await compiled.ainvoke({"messages" : [("user", query)]})

            for key, value in result.items():
                if key == "tool_calls": 
                    tool_calls = value
                elif key == "tool_outputs": 
                    tool_outputs = value
                elif key == "model_response": 
                    model_response = value
            

            data = pd.concat(data, [[index, "evaluate_model_performance", query, row['context_type'],  tool_calls, tool_outputs, model_response, category]])

        full_set = pd.to_csv(data, 'full_set.csv', index = True)

        return 0
    except Exception as e: 
        print("Error in evaluate_model_performance: ", e)
        return 1
     



""" USING THE GATHERED DATASET TO EVALUATE THE MODEL PERFORMANCE """


async def test_context_precision(query : str, context : str):
    """ this function is used in the experiment that runs in the main function and scores the retrieval of the the ai agent using an LLM as a judge"""

    

@experiment    
async def evaluate_model_performance(): 
    """ this function is to run multiple looped experiments to evaluate the model performance.
    this will gauge the model capabilities"""
    
    


    
    


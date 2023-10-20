#!/usr/bin/env python

import os
import requests
import json
import time
import re
import random
import string
import boto3
from boto3.dynamodb.conditions import Key
import pygsheets
from datetime import datetime, timedelta
import openai
import random
import string
from beem.imageuploader import ImageUploader
from beem import Hive
from beem.account import Account
from beem.nodelist import NodeList

def access_strava_activities(athlete_access_token):
    # Pass the athlete access token to strava to get activities
    bearer_header = "Bearer "  + str(athlete_access_token)
    t = datetime.now() - timedelta(days=7)
    parameters = {"after": int(t.strftime("%s"))}
    headers = {'Content-Type': 'application/json', 'Authorization': bearer_header}
    response = requests.get("https://www.strava.com/api/v3/athlete/activities?per_page=30", headers=headers, params=parameters)
    activity_data = response.json()
    return activity_data

def dynamo_access():
    client = boto3.client('dynamodb', region_name='ap-southeast-2', aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'), aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),)
    dynamodb = boto3.resource('dynamodb', region_name='ap-southeast-2', aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'), aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),)
    ddb_exceptions = client.exceptions
    return dynamodb

def refresh_access_token(athlete):
    # Update the strava access token every six hours
    athlete_vals = athlete[0]
    code_val = athlete_vals['strava_one_time']
    try:
        response = requests.post("https://www.strava.com/api/v3/oauth/token", params={'client_id': os.getenv('STRAVA_CLIENT_ID'), 'client_secret': os.getenv('STRAVA_SECRET'), 'code': code_val, 'grant_type': 'refresh_token', 'refresh_token': athlete_vals['strava_refresh_token']})
        access_info = dict()
        activity_data = response.json()
        access_info['access_token'] = activity_data['access_token']
        access_info['expires_at'] = activity_data['expires_at']
        access_info['refresh_token'] = activity_data['refresh_token']
        return access_info['access_token'], access_info['expires_at']
    except:
        print("Something went wrong trying to refresh the access token")
        return False

def process_activities(data_from_strava):
    # Take the strava data and process is how you want
    activities = []
    time.sleep(3)
    for i in data_from_strava:
        if i["type"] != "Run":
            continue
        else:
            activity_vals = []
            activity_vals.append(i["type"])
            date_val = i["start_date_local"]
            date = datetime.strptime(date_val, "%Y-%m-%dT%H:%M:%SZ")
            new_date_val = date.strftime("%Y-%m-%d")
            activity_vals.append(new_date_val)
            activity_vals.append(i["name"])
            distance = str(round(i["distance"] * .001, 2))
            activity_vals.append(distance)
            duration = str(round(i["moving_time"] / 60))
            activity_vals.append(duration)
            activity_vals.append("https://www.strava.com/activities/" + str(i["id"]))
            activity_vals.append(str(i["id"]))
            #print(activity_vals)
            activities.append(activity_vals)
    return activities

def ask_openai(api_key, prompt, max_tokens):
    openai.api_key=api_key
    endpoint='https://api.openai.com/v1/chat/completions'
    response = openai.Completion.create(
            model="text-davinci-003",
            prompt=prompt,
            max_tokens=200
            )
    return response.choices[0].text

def post_to_hive(post_athlete, post_title, post_body):
    nodelist = NodeList()
    nodelist.update_nodes()
    nodes = nodelist.get_hive_nodes()
    wif = os.getenv('POSTING_KEY')
    hive = Hive(nodes=nodes, keys=[wif])
    author = "strava2hive"
    title = post_title
    community = "hive-107275"
    body = post_body
    parse_body = True
    self_vote = False
    tags = ['exhaust', 'test', 'beta', 'runningproject', 'sportstalk']
    beneficiaries = [{'account': 'run.vince.run', 'weight': 1000},]
    permlink = "testingopenai-" + ''.join(random.choices(string.digits, k=10))
    hive.post(title, body, author=author, tags=tags, community=community, parse_body=parse_body, self_vote=self_vote, beneficiaries=beneficiaries, permlink=permlink)

# Connect to the dynamodb and get our access tokens

athlete_id = '1778XXX'
dynamoTable = 'ai_test_athletes'
dynamodb = dynamo_access()
table = dynamodb.Table(dynamoTable)
athletedb_response = table.query(KeyConditionExpression=Key('athleteId').eq(athlete_id))
strava_expire_date = athletedb_response['Items'][0]['strava_token_expires']

# Check if the tokens are expired and then request new ones if needed

expire_time = int(strava_expire_date)
current_time = time.time()
expired_value = expire_time - int(current_time)
if expired_value > 0:
    something = 4
else:
    new_access_token, new_expire_date = refresh_access_token(athletedb_response['Items'])
    table = dynamodb.Table(dynamoTable)
    athletedb_response = table.query(KeyConditionExpression=Key('athleteId').eq(athlete_id))
    dynamodb = dynamo_access()
    athlete_table = dynamodb.Table(dynamoTable)
    response = athlete_table.update_item(
            Key={ 'athleteId': athlete_id},
            UpdateExpression='SET strava_access_token = :newStravaToken', 
            ExpressionAttributeValues={':newStravaToken': str(new_access_token)}, 
            ReturnValues="UPDATED_NEW")
    response = athlete_table.update_item(Key={'athleteId': athlete_id}, UpdateExpression='SET strava_token_expires = :newStravaExpire', ExpressionAttributeValues={':newStravaExpire': new_expire_date}, ReturnValues="UPDATED_NEW")

# Use the tokens to get details from strata and process into variable “pa”

strava_access_token = athletedb_response['Items'][0]['strava_access_token']
ath_activities = access_strava_activities(strava_access_token)
pa = process_activities(ath_activities)

# New we have all the data, bring it all together to post
# Start by creating the tables

top_table = f'''
<h2>Your Training Week</h2>

<table>
  <tr>
    <th>Date</th>
    <th>Run Session</th>
    <th>Distance(km)</th>
    <th>Duration(min)</th>
  </tr>'''

for i in range(len(pa)):
    table_body = f'''
  <tr>
    <td>{pa[i][1]}</td> 
    <td>{pa[i][2]}</td> 
    <td>{pa[i][3]}</td>
    <td>{pa[i][4]}</td>
  </tr>'''  
    top_table = top_table + table_body

weeks_run_table = top_table + '\n</table>'

# Work with openai, get out API Key from variables and put together the prompts
prompt_return_val = ''
api_key = str(os.getenv('OPENAI_KEY'))

prompt = """
Please provide a summary of my training week based on the data in the following table. Include information on the total distance and any notable patterns or achievements: 
""" + weeks_run_table

prompt2 = """
Please act as a exprienced run coach and using the training data in the following table, please provide a new training week with five runs to help the run improve their running times. This training plan can be simply written as a text list:
""" + weeks_run_table

# Call the OpenAI API and get our new training plan 
prompt_return_val = ask_openai(api_key, prompt, 200)
suggested_training = ask_openai(api_key, prompt2, 200)

# Post all this data to Hive for the user
title = "AI Generated Run Coaching For Strava User Stats"
author = "strava2hive"
community = "hive-107275"
athlete = "run.vince.run"
tags = []
introduction="""
![S2HLogo.PNG](https://images.hive.blog/DQ/S2HLogo.PNG)

This is a proof of concept to integrate openai as part of an automated process to provide run coaching to users of a specific app. I do not believe that AI should be used for writing Hive posts, but I think it can be a good tool to use to help integrate extra details and information

"""
conclusion="""
Please see my posts on stemgeeks for further details and information on the process

"""

# Create the full post and then post it to Hive
post_body = introduction + weeks_run_table + prompt_return_val + suggested_training + conclusion

post_to_hive(athlete, title, post_body)

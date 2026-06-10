# OBJECTIVE
The users will provide natural language instructions to the application and the application will use local LLM to convert the natural language instructions into SQL statement. The application will run the SQL statement and produce one or more report in HTML.

# INTENT
The users want to use the application to run data quality checks on the data sets (2 or more tables). The output from the checks will be used to correct the production data. The users are expected to keep using the application on a recurring basis.

# INPUTS
- One or more CSV files (can be as big as 8GB)
- Table joins instruction in Natural Language
- Data Quality rules in Natural Language

# OUTPUTS
- Summary HTML highlighting how many records violated the rules
- Detailed HTML for each rule showing which exact records are violated
- Final joined table in CSV format

# TECHNICAL CONSTRAINTS
- An air-gapped laptop
- Laptop has up to 64GB of RAM or lesser
- A gaming quality GPU
- A local small LLM model
- Windows 10 only
- Anaconda distribution only

# Target Audience
- Business Users who has no knowledge of SQL and will provide instructions using UK or US English

# EXPECTED WORKFLOW (INITIAL)
1. User will place the CSVs to check in \data folder
2. User will start the application
3. User will choose which files to load
4. Application will provide a preview for all the loaded tables
5. User will explain how to join the tables in Natural Language
6. Application will join the tables and persist the final output
7. User will explain in Natural Language how to apply one or more data quality rules
8. Application will check the rules against the joined table
9. A summary HTML will be generated
10. One or more detailed HTML will be generated
11. Application will offer to store the data quality rules in \rules folder
12. Application will offer to store the join rules in \joins folder
13. Application will offer to store the joined tables in a CSV file

# EXPECTED WORKFLOW (RECURRING)
1. User will replace or add new CSVs files in \data folder
2. User will start the application
3. Application detected there are data quality rules in \rules folder
4. Application also detected that join rules in \joins folder
5. Application offer to automatically run the joins and data quality rules
6. If user accept the offer, do Step 6, 9, 10, 11, 12, 13 in EXPECTED WORKFLOW (INITIAL) without further interaction
7. If user rejects the offer, jump to Step 3 in EXPECTED WORKFLOW (INITIAL) and continue from there

# LLM
- Intent to use Ollama with a small LLM model that is capable of converting Natural Language to SQL
- Ensure there are configuration file stored in \config folder that allows the user to configure the local API gateway to call

# LLM CONFIG
- Ollama is the API provider
- Expected URL: http://localhost:11434
- Model: Qwen 2.5 Coder (3B or 7B) but I will name the model as "my_llm"
- Ensure i can configure the endpoint and its setting via a config file stored in \config folder

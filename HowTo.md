# Inline story → stdout
python test_suite_generator.py --story "As a user I want to reset my password via email."

# From file → save to JSON
python test_suite_generator.py --file story.txt --output test_suite.json

# Pipe from another tool
cat story.txt | python test_suite_generator.py --stdin --output suite.json

# Use a different model with debug logging
python test_suite_generator.py --file story.txt --model gpt-4-turbo --temperature 0.1 --log-level DEBUG
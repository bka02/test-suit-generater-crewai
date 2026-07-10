from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task

from .models import AssembledSuite


@CrewBase
class QACrew:
    """QA Test Suite Crew — generates structured test suites from user stories."""

    agents: list[BaseAgent]
    tasks: list[Task]

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def story_analyst(self) -> Agent:
        return Agent(config=self.agents_config["story_analyst"])

    @agent
    def happy_path_designer(self) -> Agent:
        return Agent(config=self.agents_config["happy_path_designer"])

    @agent
    def edge_case_designer(self) -> Agent:
        return Agent(config=self.agents_config["edge_case_designer"])

    @agent
    def security_designer(self) -> Agent:
        return Agent(config=self.agents_config["security_designer"])

    @agent
    def qa_reviewer(self) -> Agent:
        return Agent(config=self.agents_config["qa_reviewer"])

    @task
    def analyse_story_task(self) -> Task:
        return Task(config=self.tasks_config["analyse_story_task"])

    @task
    def happy_path_task(self) -> Task:
        return Task(
            config=self.tasks_config["happy_path_task"],
            context=[self.analyse_story_task()],
        )

    @task
    def edge_case_task(self) -> Task:
        return Task(
            config=self.tasks_config["edge_case_task"],
            context=[self.analyse_story_task()],
        )

    @task
    def security_task(self) -> Task:
        return Task(
            config=self.tasks_config["security_task"],
            context=[self.analyse_story_task()],
        )

    @task
    def assemble_suite_task(self) -> Task:
        return Task(
            config=self.tasks_config["assemble_suite_task"],
            context=[
                self.analyse_story_task(),
                self.happy_path_task(),
                self.edge_case_task(),
                self.security_task(),
            ],
            output_pydantic=AssembledSuite,
        )

    @crew
    def crew(self) -> Crew:
        """Creates the QA Test Suite Crew."""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )

package com.architecture.resources;

import java.util.List;

import software.amazon.awscdk.Duration;
import software.amazon.awscdk.services.iam.Effect;
import software.amazon.awscdk.services.iam.PolicyStatement;
import software.amazon.awscdk.services.logs.LogGroup;
import software.amazon.awscdk.services.logs.RetentionDays;
import software.amazon.awscdk.services.stepfunctions.Chain;
import software.amazon.awscdk.services.stepfunctions.Fail;
import software.amazon.awscdk.services.stepfunctions.LogLevel;
import software.amazon.awscdk.services.stepfunctions.LogOptions;
import software.amazon.awscdk.services.stepfunctions.StateMachine;
import software.amazon.awscdk.services.stepfunctions.StateMachineType;
import software.amazon.awscdk.services.stepfunctions.TaskInput;
import software.amazon.awscdk.services.stepfunctions.tasks.LambdaInvoke;
import software.constructs.Construct;

public class StepfunctionResources extends Construct {

    private final StateMachine stateMachine;

    public StepfunctionResources(
            final Construct scope,
            final String id,
            final String stateMachineName,
            final LambdaResources lambdaResources
    ) {
        super(scope, id);

        LogGroup logGroup = LogGroup.Builder.create(this, "WorkflowLogGroup")
                .retention(RetentionDays.ONE_WEEK)
                .build();

        Fail validationFailed = Fail.Builder.create(this, "ValidationFailed")
                .cause("Validation step failed")
                .build();

        Fail prepareFailed = Fail.Builder.create(this, "PrepareFailed")
                .cause("Prepare step failed")
                .build();

        Fail executeFailed = Fail.Builder.create(this, "ExecuteFailed")
                .cause("Execute step failed")
                .build();

        Fail finalizeFailed = Fail.Builder.create(this, "FinalizeFailed")
                .cause("Finalize step failed")
                .build();

        LambdaInvoke validateInput = LambdaInvoke.Builder.create(this, "ValidateInput")
                .lambdaFunction(lambdaResources.getValidateInputFunction())
                .payload(TaskInput.fromJsonPathAt("$"))
                .outputPath("$.Payload")
                .build();
        validateInput.addCatch(validationFailed);

        LambdaInvoke generateArchitectureDoc = LambdaInvoke.Builder.create(this, "GenerateArchitectureDoc")
                .lambdaFunction(lambdaResources.getGenerateArchitectureDocFunction())
                .payload(TaskInput.fromJsonPathAt("$"))
                .outputPath("$.Payload")
                .build();
        generateArchitectureDoc.addCatch(prepareFailed);

        LambdaInvoke generateCdkCode = LambdaInvoke.Builder.create(this, "GenerateCdkCode")
                .lambdaFunction(lambdaResources.getGenerateCdkCodeFunction())
                .payload(TaskInput.fromJsonPathAt("$"))
                .outputPath("$.Payload")
                .build();
        generateCdkCode.addCatch(executeFailed);

        LambdaInvoke createGithubPr = LambdaInvoke.Builder.create(this, "CreateGithubPr")
                .lambdaFunction(lambdaResources.getCreateGithubPrFunction())
                .payload(TaskInput.fromJsonPathAt("$"))
                .outputPath("$.Payload")
                .build();
        createGithubPr.addCatch(finalizeFailed);

        Chain definition = Chain.start(validateInput)
                .next(generateArchitectureDoc)
                .next(generateCdkCode)
                .next(createGithubPr);

        this.stateMachine = StateMachine.Builder.create(this, "NewInfraCreationStateMachine")
                .stateMachineName(stateMachineName)
                .definition(definition)
                .stateMachineType(StateMachineType.STANDARD)
                .timeout(Duration.minutes(15))
                .logs(LogOptions.builder()
                        .destination(logGroup)
                        .level(LogLevel.ALL)
                        .includeExecutionData(true)
                        .build())
                .build();

        this.stateMachine.getRole().addToPrincipalPolicy(
                PolicyStatement.Builder.create()
                        .effect(Effect.ALLOW)
                        .actions(List.of("lambda:InvokeFunction"))
                        .resources(List.of(
                                lambdaResources.getValidateInputFunction().getFunctionArn(),
                                lambdaResources.getGenerateArchitectureDocFunction().getFunctionArn(),
                                lambdaResources.getGenerateCdkCodeFunction().getFunctionArn(),
                                lambdaResources.getCreateGithubPrFunction().getFunctionArn()
                        ))
                        .build()
        );
    }

    public StateMachine getStateMachine() {
        return stateMachine;
    }
}

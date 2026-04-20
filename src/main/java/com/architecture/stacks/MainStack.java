package com.architecture.stacks;

import com.architecture.resources.LambdaResources;
import com.architecture.resources.S3Resources;
import com.architecture.resources.StepfunctionResources;
import software.amazon.awscdk.CfnOutput;
import software.amazon.awscdk.CfnOutputProps;
import software.amazon.awscdk.Stack;
import software.amazon.awscdk.StackProps;
import software.constructs.Construct;

public class MainStack extends Stack {

    public MainStack(final Construct scope, final String id) {
        this(scope, id, null);
    }

    public MainStack(final Construct scope, final String id, final StackProps props) {
        super(scope, id, props);

        String inputImageBucketName =
                String.valueOf(getNode().tryGetContext("inputImageBucketName"));
        String architectureDocBucketName =
                String.valueOf(getNode().tryGetContext("architectureDocBucketName"));
        String generatedCodeBucketName =
                String.valueOf(getNode().tryGetContext("generatedCodeBucketName"));
        String githubSecretName =
                String.valueOf(getNode().tryGetContext("githubSecretName"));
        String stateMachineName =
                String.valueOf(getNode().tryGetContext("stateMachineName"));

        S3Resources s3Resources = new S3Resources(
                this,
                "S3Resources",
                inputImageBucketName,
                architectureDocBucketName,
                generatedCodeBucketName
        );

        LambdaResources lambdaResources = new LambdaResources(
                this,
                "LambdaResources",
                s3Resources,
                githubSecretName
        );

        StepfunctionResources stepfunctionResources = new StepfunctionResources(
                this,
                "StepfunctionResources",
                stateMachineName,
                lambdaResources
        );

        lambdaResources.getStartWorkflowFunction()
                .addEnvironment("STATE_MACHINE_ARN", stepfunctionResources.getStateMachine().getStateMachineArn());

        stepfunctionResources.getStateMachine().grantStartExecution(lambdaResources.getStartWorkflowFunction());

        new CfnOutput(this, "StateMachineArnOutput", CfnOutputProps.builder()
                .value(stepfunctionResources.getStateMachine().getStateMachineArn())
                .build());

        new CfnOutput(this, "StartWorkflowLambdaNameOutput", CfnOutputProps.builder()
                .value(lambdaResources.getStartWorkflowFunction().getFunctionName())
                .build());
    }
}
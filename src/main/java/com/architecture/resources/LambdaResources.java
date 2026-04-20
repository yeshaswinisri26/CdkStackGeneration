package com.architecture.resources;

import java.util.List;
import java.util.Map;
import java.util.Objects;

import com.architecture.stacks.MainStack;
import software.amazon.awscdk.Duration;
import software.amazon.awscdk.Size;
import software.amazon.awscdk.services.iam.Effect;
import software.amazon.awscdk.services.iam.ManagedPolicy;
import software.amazon.awscdk.services.iam.PolicyStatement;
import software.amazon.awscdk.services.iam.Role;
import software.amazon.awscdk.services.iam.ServicePrincipal;
import software.amazon.awscdk.services.lambda.Architecture;
import software.amazon.awscdk.services.lambda.Code;
import software.amazon.awscdk.services.lambda.Function;
import software.amazon.awscdk.services.lambda.Runtime;
import software.amazon.awscdk.services.secretsmanager.ISecret;
import software.amazon.awscdk.services.secretsmanager.Secret;
import software.constructs.Construct;

public class LambdaResources extends Construct {

    private final Function validateInputFunction;
    private final Function generateArchitectureDocFunction;
    private final Function generateCdkCodeFunction;
    private final Function createGithubPrFunction;
    private final Function startWorkflowFunction;

    public LambdaResources(
            final Construct scope,
            final String id,
            final S3Resources s3Resources,
            final String githubSecretName
    ) {
        super(scope, id);

        ISecret githubSecret = Secret.fromSecretNameV2(this, "GitHubSecret", githubSecretName);

        Role validateInputRole = buildBasicLambdaRole("ValidateInputLambdaRole");
        Role generateArchitectureDocRole = buildBasicLambdaRole("GenerateArchitectureDocLambdaRole");
        Role generateCdkCodeRole = buildBasicLambdaRole("GenerateCdkCodeLambdaRole");
        Role createGithubPrRole = buildBasicLambdaRole("CreateGithubPrLambdaRole");
        Role startWorkflowRole = buildBasicLambdaRole("StartWorkflowLambdaRole");

        this.validateInputFunction = Function.Builder.create(this, "ValidateInputLambda")
                .functionName("ValidateInputLambda")
                .runtime(Runtime.PYTHON_3_12)
                .architecture(Architecture.X86_64)
                .handler("app.lambda_handler")
                .code(Code.fromAsset("lambda/validate_input"))
                .timeout(Duration.seconds(30))
                .memorySize(512)
                .role(validateInputRole)
                .environment(Map.of(
                        "GITHUB_SECRET_NAME", githubSecretName
                ))
                .build();

        this.generateArchitectureDocFunction = Function.Builder.create(this, "GenerateArchitectureDocLambda")
                .functionName("GenerateArchitectureDocLambda")
                .runtime(Runtime.PYTHON_3_12)
                .architecture(Architecture.X86_64)
                .handler("app.lambda_handler")
                .code(Code.fromAsset("lambda/generate_architecture_doc"))
                .timeout(Duration.minutes(5))
                .memorySize(1024)
                .ephemeralStorageSize(Size.mebibytes(1024))
                .role(generateArchitectureDocRole)
                .environment(Map.of(
                        "BEDROCK_REGION", "ap-southeast-2",
                        "S3_REGION", "ap-southeast-2",
                        "MODEL_ID", "global.anthropic.claude-sonnet-4-6"
                ))
                .build();

        this.generateCdkCodeFunction = Function.Builder.create(this, "GenerateCdkCodeLambda")
                .functionName("GenerateCDKCodeFromArchDoc")
                .runtime(Runtime.PYTHON_3_12)
                .architecture(Architecture.X86_64)
                .handler("app.lambda_handler")
                .code(Code.fromAsset("lambda/generate_cdk_code"))
                .timeout(Duration.minutes(10))
                .memorySize(2048)
                .ephemeralStorageSize(Size.mebibytes(2048))
                .role(generateCdkCodeRole)
                .environment(Map.of(
                        "BEDROCK_REGION", "ap-southeast-2",
                        "S3_REGION", "ap-southeast-2",
                        "MODEL_ID", "global.anthropic.claude-sonnet-4-6"
                ))
                .build();

        this.createGithubPrFunction = Function.Builder.create(this, "CreateGithubPrLambda")
                .functionName("CreateGithubPrLambda")
                .runtime(Runtime.PYTHON_3_12)
                .architecture(Architecture.X86_64)
                .handler("app.lambda_handler")
                .code(Code.fromAsset("lambda/create_github_pr"))
                .timeout(Duration.minutes(5))
                .memorySize(1024)
                .ephemeralStorageSize(Size.mebibytes(1024))
                .role(createGithubPrRole)
                .environment(Map.of(
                        "GITHUB_SECRET_NAME", githubSecretName,
                        "TMP_EXTRACT_DIR", "/tmp/extracted"
                ))
                .build();

        this.startWorkflowFunction = Function.Builder.create(this, "StartWorkflowLambda")
                .functionName("StartNewInfraWorkflowLambda")
                .runtime(Runtime.PYTHON_3_12)
                .architecture(Architecture.X86_64)
                .handler("app.lambda_handler")
                .code(Code.fromAsset("lambda/start_workflow"))
                .timeout(Duration.seconds(30))
                .memorySize(512)
                .role(startWorkflowRole)
                .build();

        grantS3Permissions(s3Resources);
        grantSecretPermissions(githubSecret);
        grantBedrockPermissions(generateArchitectureDocRole, generateCdkCodeRole);
    }

    private Role buildBasicLambdaRole(final String id) {
        return Role.Builder.create(this, id)
                .assumedBy(new ServicePrincipal("lambda.amazonaws.com"))
                .managedPolicies(List.of(
                        ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaBasicExecutionRole")
                ))
                .build();
    }

    private void grantS3Permissions(final S3Resources s3Resources) {
        s3Resources.getInputImageBucket().grantRead(validateInputFunction);
        s3Resources.getInputImageBucket().grantRead(generateArchitectureDocFunction);

        s3Resources.getArchitectureDocBucket().grantReadWrite(generateArchitectureDocFunction);
        s3Resources.getArchitectureDocBucket().grantRead(generateCdkCodeFunction);

        s3Resources.getGeneratedCodeBucket().grantReadWrite(generateCdkCodeFunction);
        s3Resources.getGeneratedCodeBucket().grantRead(createGithubPrFunction);

        Objects.requireNonNull(validateInputFunction.getRole()).addToPrincipalPolicy(
                PolicyStatement.Builder.create()
                        .effect(Effect.ALLOW)
                        .actions(List.of("s3:HeadObject", "s3:GetObject"))
                        .resources(List.of(s3Resources.getInputImageBucket().arnForObjects("*")))
                        .build()
        );

        validateInputFunction.getRole().addToPrincipalPolicy(
                PolicyStatement.Builder.create()
                        .effect(Effect.ALLOW)
                        .actions(List.of("s3:ListBucket"))
                        .resources(List.of(s3Resources.getInputImageBucket().getBucketArn()))
                        .build()
        );

        Objects.requireNonNull(createGithubPrFunction.getRole()).addToPrincipalPolicy(
                PolicyStatement.Builder.create()
                        .effect(Effect.ALLOW)
                        .actions(List.of("s3:GetObject"))
                        .resources(List.of(s3Resources.getGeneratedCodeBucket().arnForObjects("*")))
                        .build()
        );

        createGithubPrFunction.getRole().addToPrincipalPolicy(
                PolicyStatement.Builder.create()
                        .effect(Effect.ALLOW)
                        .actions(List.of("s3:ListBucket"))
                        .resources(List.of(s3Resources.getGeneratedCodeBucket().getBucketArn()))
                        .build()
        );
    }

    private void grantSecretPermissions(final ISecret githubSecret) {
        githubSecret.grantRead(validateInputFunction);
        githubSecret.grantRead(createGithubPrFunction);
    }

    private void grantBedrockPermissions(
            final Role generateArchitectureDocRole,
            final Role generateCdkCodeRole
    ) {
        PolicyStatement bedrockPolicy = PolicyStatement.Builder.create()
                .effect(Effect.ALLOW)
                .actions(List.of(
                        "bedrock:InvokeModel",
                        "bedrock:InvokeModelWithResponseStream"
                ))
                .resources(List.of(
                        "arn:aws:bedrock:ap-southeast-2:221082200102:inference-profile/global.anthropic.claude-sonnet-4-6",
                        "arn:aws:bedrock:ap-southeast-2::foundation-model/anthropic.claude-sonnet-4-6",
                        "arn:aws:bedrock:::foundation-model/anthropic.claude-sonnet-4-6"
                ))
                .build();

        generateArchitectureDocRole.addToPolicy(bedrockPolicy);
        generateCdkCodeRole.addToPolicy(bedrockPolicy);
    }

    public Function getValidateInputFunction() {
        return validateInputFunction;
    }

    public Function getGenerateArchitectureDocFunction() {
        return generateArchitectureDocFunction;
    }

    public Function getGenerateCdkCodeFunction() {
        return generateCdkCodeFunction;
    }

    public Function getCreateGithubPrFunction() {
        return createGithubPrFunction;
    }

    public Function getStartWorkflowFunction() {
        return startWorkflowFunction;
    }
}

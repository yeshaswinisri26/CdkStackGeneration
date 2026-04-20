package com.architecture.resources;

import software.amazon.awscdk.services.s3.Bucket;
import software.amazon.awscdk.services.s3.IBucket;
import software.constructs.Construct;

public class S3Resources extends Construct {

    private final IBucket inputImageBucket;
    private final IBucket architectureDocBucket;
    private final IBucket generatedCodeBucket;

    public S3Resources(
            final Construct scope,
            final String id,
            final String inputImageBucketName,
            final String architectureDocBucketName,
            final String generatedCodeBucketName
    ) {
        super(scope, id);

        this.inputImageBucket = Bucket.fromBucketName(this, "InputImageBucket", inputImageBucketName);
        this.architectureDocBucket = Bucket.fromBucketName(this, "ArchitectureDocBucket", architectureDocBucketName);
        this.generatedCodeBucket = Bucket.fromBucketName(this, "GeneratedCodeBucket", generatedCodeBucketName);
    }

    public IBucket getInputImageBucket() {
        return inputImageBucket;
    }

    public IBucket getArchitectureDocBucket() {
        return architectureDocBucket;
    }

    public IBucket getGeneratedCodeBucket() {
        return generatedCodeBucket;
    }
}
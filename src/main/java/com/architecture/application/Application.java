package com.architecture.application;

import com.architecture.stacks.MainStack;
import software.amazon.awscdk.App;

public class Application {
    public static void main(final String[] args) {
        App app = new App();
        new MainStack(app, "BedrockCdkWorkflowStack");
        app.synth();
    }
}

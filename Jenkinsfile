pipeline {
    agent {
        // Change this label to the exact one defined in your Jenkins aws-ec2-cloud AMI template
        label 'ec2-dynamic-agent' 
    }

    environment {
        LAMBDA_FUNCTION_NAME = 'SlackAwsCostBotRole'
        DEPLOYMENT_ZIP = 'deployment.zip'
        BUILD_DIR = 'build'
        AWS_REGION = 'ap-south-1' // Extracted from your IAM policies
    }

    stages {
        stage('Package Code') {
            steps {
                script {
                    sh """
                        echo "Running on EC2 Agent: \$(hostname)"
                        
                        # Clean up previous builds
                        rm -rf ${BUILD_DIR} ${DEPLOYMENT_ZIP}
                        mkdir -p ${BUILD_DIR}
                        
                        # IMPORTANT: Ensure pandas is NOT in requirements.txt
                        pip install -r requirements.txt -t ${BUILD_DIR} --quiet
                        
                        # Copy source files
                        cp app.py pricing_logic.py main.py ${BUILD_DIR}/
                        
                        # Zip the contents of the folder
                        cd ${BUILD_DIR} && zip -r ../${DEPLOYMENT_ZIP} . --quiet
                    """
                }
            }
        }
        
        stage('Deploy to Lambda') {
            steps {
                script {
                    // This command inherits the IAM role attached to the EC2 agent instance
                    sh """
                        aws lambda update-function-code \
                            --function-name ${LAMBDA_FUNCTION_NAME} \
                            --zip-file fileb://${DEPLOYMENT_ZIP} \
                            --region ${AWS_REGION}
                    """
                }
            }
        }
    }

    post {
        always {
            echo "Cleaning up workspace..."
            sh "rm -rf ${BUILD_DIR} ${DEPLOYMENT_ZIP}"
        }
        success {
            echo "✅ Lambda function '${LAMBDA_FUNCTION_NAME}' packaged and updated successfully."
        }
        failure {
            echo "❌ Pipeline failed. Check the logs for packaging or AWS CLI deployment errors."
        }
    }
}
pipeline {
    agent {
        // Uses the EC2 agent template you configured
        label 'aws-ec2-cloud' 
    }

    environment {
        LAMBDA_FUNCTION_NAME = 'SlackAwsCostBotRole'
        DEPLOYMENT_ZIP = 'deployment.zip'
        BUILD_DIR = 'build'
        AWS_REGION = 'ap-south-1' 
    }

    stages {
        stage('Package Code') {
            steps {
                script {
                    sh """
                        echo "Running on EC2 Agent: \$(hostname)"
                        
                        # 1. Install missing Ubuntu dependencies
                        sudo apt-get update -y
                        sudo apt-get install -y python3-pip zip
                        
                        # 2. Clean up previous builds
                        rm -rf ${BUILD_DIR} ${DEPLOYMENT_ZIP}
                        mkdir -p ${BUILD_DIR}
                        
                        # 3. Explicitly install ONLY the lightweight libraries (Ignore requirements.txt)
                        pip3 install slack_bolt requests openpyxl -t ${BUILD_DIR} --quiet
                        
                        # 4. Copy source files
                        cp app.py pricing_logic.py main.py ${BUILD_DIR}/
                        
                        # 5. Zip the contents of the folder
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
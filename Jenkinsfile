pipeline {
    agent {
        // Uses the EC2 agent template you configured
        label 'ec2-dynamic-agent' 
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

                        wait_for_apt_locks() {
                            echo "Waiting for dpkg/apt locks to be released..."
                            for i in \$(seq 1 60); do
                                if ! sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 \\
                                    && ! sudo fuser /var/lib/dpkg/lock >/dev/null 2>&1 \\
                                    && ! sudo fuser /var/cache/apt/archives/lock >/dev/null 2>&1 \\
                                    && ! sudo fuser /var/lib/apt/lists/lock >/dev/null 2>&1; then
                                    return 0
                                fi

                                echo "Lock held, waiting 5 seconds..."
                                sleep 5
                            done

                            echo "Timed out waiting for apt/dpkg locks."
                            return 1
                        }

                        ensure_system_packages() {
                            if command -v pip3 >/dev/null 2>&1 && command -v zip >/dev/null 2>&1; then
                                echo "pip3 and zip already installed; skipping apt-get."
                                return 0
                            fi

                            sudo systemctl stop unattended-upgrades apt-daily.service apt-daily.timer apt-daily-upgrade.service apt-daily-upgrade.timer || true
                            wait_for_apt_locks

                            sudo apt-get update -y
                            wait_for_apt_locks
                            sudo apt-get install -y -o DPkg::Lock::Timeout=300 python3-pip zip
                        }

                        # 1. Ensure packaging tools exist before building the Lambda zip
                        ensure_system_packages
                        
                        # 2. Clean up previous builds
                        rm -rf ${BUILD_DIR} ${DEPLOYMENT_ZIP}
                        mkdir -p ${BUILD_DIR}
                        
                        # 3. Install the Lambda runtime dependencies needed by app.py and pricing_logic.py
                        python3 -m pip install slack_bolt requests openpyxl -t ${BUILD_DIR} --quiet
                        
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

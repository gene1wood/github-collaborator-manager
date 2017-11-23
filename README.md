A tool to manage GitHub repo collaborators with files

* [The problem to solve](#the-problem-to-solve)
* [How GitHub Collaborator Manager solves this](#how-github-collaborator-manager-solves-this)
* [Security implications](#security-implications)
* [Prerequisites](#prerequisites)
* [One time setup](#one-time-setup)
* [Enabling collaborator manager on a repo](#enabling-collaborator-manager-on-a-repo)
* [`collaborators.yaml` format](#collaboratorsyaml-format)
  * [Inherited collaborators](#inherited-collaborators)
* [Why don't we have to configure which GitHub webhooks to trigger on?](#why-dont-we-have-to-configure-which-github-webhooks-to-trigger-on)

# The problem to solve

You've got a group of people who you want to collaborate with in multiple
private repositories but you don't want to [pay for GitHub organizations](https://github.com/pricing)
 (which would be $135/month for 15 people). You also don't want to manually go
and either add new collaborators or remove existing collaborators from *all* the
different private repos, instead you want to be able to manage groups of
collaborators and associate each private repo with one of those groups. You also
want to enable all of your contributors to manage who is and isn't a
collaborator.

# How GitHub Collaborator Manager solves this

GitHub Collaborator Manager (GCM) allows you to create a file in each of your
private repos which lists the collaborators that that repo should have. These
collaborator files can list either GitHub users, or other repos which have
collaborator files in them so that you can set a repo to have the same
collaborators as another repo.

Each time a collaborator file is updated, AWS Lambda updates the GitHub
settings for that repo (and all dependent repos) to reflect the added or
removed collaborators.

# Security implications

For private repos on which you enable GCM, GCM intentionally grants any user who
can already push code to that repo the ability to add and remove collaborators.

# Prerequisites

* A paid GitHub user ($7/month) who can create private repos
* A free Amazon Web Services (AWS) account. This requires a credit card but GCM
  will not incur any charges as it uses exclusively services in their free tier.

# One time setup

* Provision a [GitHub personal token](https://github.com/settings/tokens) with
  `repo` scope permissions.
  ![GitHub personal token dialog](https://raw.githubusercontent.com/gene1wood/github-collaborator-manager/master/docs/github-personal-token-scope.png)
* Create a `config.yaml` with GitHub personal token. The file would look like
  this:

      github_token: 0123456789abcdef0123456789abcdef01234567

* Zip up github_collaborator_manager, it's dependencies and the `config.yaml`

      tmpdir=`mktemp -d`
      pip install agithub PyYAML python-dateutil --target "$tmpdir"
      cwd=`pwd`
      pushd "$tmpdir"
      zip -r "${cwd}/github_collaborator_manager.zip" *
      popd
      rm -rf "$tmpdir"
      zip --junk-paths github_collaborator_manager.zip github_collaborator_manager/__init__.py
      chmod 644 github_collaborator_manager/config.yaml;zip --junk-paths github_collaborator_manager.zip github_collaborator_manager/config.yaml;chmod 600 github_collaborator_manager/config.yaml
        
* Create an AWS IAM role to be used by a AWS Lambda function with `LambdaBasicExecution`

      echo '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":["lambda.amazonaws.com"]},"Action":["sts:AssumeRole"]}]}' | aws iam create-role --role-name github-collaborator-manager --assume-role-policy-document file:///dev/stdin
      aws iam attach-role-policy --role-name github-collaborator-manager --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

* Deploy the zip artifact to Lambda

      role_arn="`aws iam get-role --role-name github-collaborator-manager --output text --query 'Role.Arn'`"
      lambda_arn="`aws lambda create-function --function-name github-collaborator-manager --runtime python2.7 --timeout 30 --role $role_arn --handler __init__.lambda_handler --zip-file fileb://github_collaborator_manager.zip --query 'FunctionArn' --output text`"
      echo "Created Lambda function $lambda_arn"

* Create SNS Topic

      topic_arn=`aws sns create-topic --name GithubWebhookTopic --output text --query 'TopicArn'`
      aws sns create-topic --name GithubWebhookTopic --output table --query '{"Sns topic":TopicArn}'
      a=(${topic_arn//:/ });echo "Sns region : ${a[3]}"

* Update Lambda function resource policy to grant SNS rights to invoke it

      aws lambda add-permission --function-name github-collaborator-manager --statement-id GiveSNSPermissionToInvokeFunction --action lambda:InvokeFunction --principal sns.amazonaws.com --source-arn $topic_arn

* Subscribe the Lambda function to the SNS topic

      aws sns subscribe --topic-arn $topic_arn --protocol lambda --notification-endpoint $lambda_arn

* Create IAM User to be used by GitHub

      aws iam create-user --user-name github-sns-publisher
      echo "{\"Version\": \"2012-10-17\",\"Statement\": [{\"Action\": [\"sns:Publish\"],\"Resource\": [\"${topic_arn}\"],\"Effect\": \"Allow\"}]}" | aws iam put-user-policy --user-name github-sns-publisher --policy-name PublishToSNS --policy-document file:///dev/stdin
      aws iam create-access-key --user-name github-sns-publisher --output table --query 'AccessKey.{"Aws Key":AccessKeyId, "Aws secret":SecretAccessKey}'

# Enabling collaborator manager on a repo

1. Configure GitHub SNS integration using the AWS IAM user API keys generated above
   by browsing to the repo you want to enable, clicking "Settings", clicking
   "Integrations & services" in the left column, clicking the "Add service"
   button, typing "SNS" in the filter field to search for "Amazon SNS"
    * Enter the `Aws key`, `Sns topic`, `Sns region` and `Aws secret` created above
      in each repo you want managed

2. Create a `.well-known/collaborators.yaml` file in the repo and the collaborator
   manager will process the file when it's created (or updated)

# `collaborators.yaml` format

```yaml
collaborators:
- octocat
- mojombo
```

The `collaborators.yaml` file which is located in any repo at `.well-known/collaborators.yaml`
contains a map with at least one key, `collaborators`. The value for that key is a 
list of GitHub usernames that you want to be the collaborators on the repo.

## Inherited collaborators

In addtion to GitHub usernames in the `collaborators` list, you can add
references to other GitHub repos that you would like to inherit a collaborators
list from.

For example if you created a collaborators file in your repo and added a line
like 

```yaml
collaborators:
- octocat
- mojombo
- octocat/Spoon-Knife
```
    
the collaborator manager would not only add `octocat` and `mojobo` as
collaborators it would also fetch the collaborator file
https://github.com/octocat/Spook-Knife/blob/master/.well-known/collaborators.yaml
and add all of the collaborates in that file as collaborators on your repo.

It would also traverse any other repos referenced in the `octocat/Spoon-Knife`
collaborator file.

Additionally, if later, the `octocat/Spoon-Knife` collaborator file was updated
those added or removed users would also be added or removed from your repo that
references that collaborator file.

If you reference a collaborator file, make sure to also update the *referenced*
repository to link back using a `child_repos` key.

<table>
<tr><th><code>octocat/Fork-Chopstick</code></th><th><code>octocat/Spoon-Knife</code></th></tr>
<tr><td>
   <pre lang="yaml">
collaborators:
- octocat
- mojombo
- octocat/Spoon-Knife
   </pre>
</td>
<td>
  <pre lang="yaml">
collaborators:
- defunkt
- pjhyett
child_repos:
- octocat/Fork-Chopstick
  </pre>
</td>
</tr>
</table>

# Why don't we have to configure which GitHub webhooks to trigger on?

By default `push` is the
one action that a webhook is enabled for so nothing needs to be done to enable
this webhook action when the GitHub Amazon SNS integration is enabled. If
this weren't the case you'd need to add the action via the API because it 
can't be done through the GitHub web UI. Here's example python code to do it
using the API. To do so you'll need a GitHub personal token with the 
`write:repo_hook` permission

      from agithub.GitHub import GitHub
      g = GitHub(token=GITHUB_TOKEN_WITH_WRITE_REPO_HOOK_PERMISSIONS)
      status, hooks = g.repos[OWNER][REPO_NAME].hooks.get()
      new_event = 'push'
      for hook in [x for x in hooks if x['name'] == 'amazonsns']:
          if new_event not in hook['events']:
              status, result = g.repos[OWNER][REPO_NAME].hooks[hook['id']].patch(add_events=[new_event])

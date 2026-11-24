// Foundry resource + project + two model deployments, Azure AI Search, and role assignments.
targetScope = 'resourceGroup'

@description('Object ID of the user who will run the app: az ad signed-in-user show --query id -o tsv')
param principalId string
@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'
param location string = resourceGroup().location
param searchLocation string = location
@allowed(['basic', 'standard'])
param searchSku string = 'basic'
param chatModel string = 'gpt-5.4-mini'
param chatModelVersion string = '2026-03-17'
@description('Thousands of tokens per minute. Lower it if your quota is small.')
param chatCapacity int = 20
param embeddingCapacity int = 20

var suffix = uniqueString(resourceGroup().id)
var foundryName = 'rag-foundry-${suffix}'
var projectName = 'rag-project'

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: foundryName
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    allowProjectManagement: true
    customSubDomainName: foundryName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: projectName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {}
}

resource chat 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: 'chat'
  sku: { name: 'GlobalStandard', capacity: chatCapacity }
  properties: {
    model: { format: 'OpenAI', name: chatModel, version: chatModelVersion }
  }
  dependsOn: [project]
}

resource embedding 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: 'embedding'
  sku: { name: 'GlobalStandard', capacity: embeddingCapacity }
  properties: {
    model: { format: 'OpenAI', name: 'text-embedding-3-small', version: '1' }
  }
  dependsOn: [chat] // deployments on one account must be created one at a time
}

resource search 'Microsoft.Search/searchServices@2025-05-01' = {
  name: 'rag-search-${suffix}'
  location: searchLocation
  sku: { name: searchSku }
  properties: {
    disableLocalAuth: true
    semanticSearch: 'free'
    replicaCount: 1
    partitionCount: 1
  }
}

var foundryUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var searchRoles = [
  '7ca78c08-252a-4471-8644-bb5ff32d4ba0' // Search Service Contributor: create the index
  '8ebe5a00-799e-43f5-93ac-243d3dce84a7' // Search Index Data Contributor: read and write documents
]

resource foundryRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, principalId, foundryUser)
  scope: foundry
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', foundryUser)
  }
}

resource searchRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in searchRoles: {
  name: guid(search.id, principalId, role)
  scope: search
  properties: {
    principalId: principalId
    principalType: principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role)
  }
}]

output PROJECT_ENDPOINT string = 'https://${foundryName}.services.ai.azure.com/api/projects/${projectName}'
output OPENAI_ENDPOINT string = 'https://${foundryName}.openai.azure.com/openai/v1/'
output SEARCH_ENDPOINT string = 'https://${search.name}.search.windows.net'
